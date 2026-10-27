"""Checkpoint each assessment without changing rule revisions, statuses or approvals."""
from copy import deepcopy
import logging
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from routing_guides.analysis_provider import ProviderFailure
from routing_guides.assessment import assessment_fingerprint, related_rules, duplicate_index, new_assessment_job
from routing_guides.assessment_provider import assess
from routing_guides.connections import connection
from routing_guides.db import sessions
from routing_guides.models import AnalysisRun, AuditEvent, GuidePage
from routing_guides.storage import guide_directory
from routing_guides.tasks import assess_guide_rules

logger = logging.getLogger(__name__)


async def queue_initial_assessment(session: AsyncSession, run: AnalysisRun, payload: dict) -> None:
    """Commit extraction completion and its follow-up job atomically, at most once."""
    if not run.config.get('assess_rules') or payload.get('assessment_job'):
        return
    selected = [rule for rule in payload['rules'] if rule['status'] == 'pending']
    config = await connection('jev') if selected else {'model': '', 'key': ''}
    job = new_assessment_job(selected, config['model'], 'Initial analysis', 'all')
    payload['assessment_job'] = job
    if not selected:
        return
    if not config['model'] or not config['key']:
        job.update(status='failed', reason='configuration_required',
                   error='Set up automated checks in Connections, then check all rules. Extracted rules are saved.')
        return
    # Procrastinate uses the existing psycopg connection without committing it.
    sql_connection = await session.connection()
    raw_connection = await sql_connection.get_raw_connection()
    await assess_guide_rules.configure(connection=raw_connection.driver_connection,
        lock=f'assessment:{run.id}', queueing_lock=f'assessment:{run.id}').defer_async(
            run_id=str(run.id), job_id=job['id'])


async def run_assessment(run_id: UUID, job_id: str):
    rule_id = None
    try:
        while True:
            async with sessions.begin() as session:
                run = await session.get(AnalysisRun, run_id, with_for_update=True)
                job = (run.payload.get('assessment_job') or {}) if run else {}
                if not run or run.status != 'complete' or job.get('id') != job_id or job.get('status') in {'complete', 'cancelled'}:
                    return
                data = deepcopy(run.payload)
                job = data['assessment_job']
                if not job['pending']:
                    job['status'] = 'complete'
                    run.payload, run.version = data, run.version + 1
                    return
                job['status'], job['error'] = 'running', None
                item = job['pending'][0]
                rule_id = item['id']
                candidate = next((r for r in data['rules'] if r['id'] == rule_id), None)
                if not candidate or candidate['status'] != 'pending' or candidate['revision'] != item['revision']:
                    job['pending'].pop(0)
                    job['processed'] += 1
                    job['skipped'] += 1
                    run.payload, run.version = data, run.version + 1
                    continue
                related = deepcopy(related_rules(candidate, duplicate_index(data['rules'])))
                candidate = deepcopy(candidate)
                fingerprint = assessment_fingerprint(candidate, related)
                source_id = UUID(candidate.get('source_guide_id') or str(run.guide_id))
                indices = {index for e in candidate['spec']['evidence']
                           for index in (e['page'] - 2, e['page'] - 1, e['page']) if index >= 0}
                source = (await session.execute(select(GuidePage.page_index, GuidePage.text).where(
                    GuidePage.guide_id == source_id, GuidePage.page_index.in_(indices)))).all()
                pages = {p.page_index + 1: p.text for p in source}
                settings = deepcopy(job)
                guide_id = run.guide_id
                run.payload = data
            path = guide_directory(guide_id) / 'assessment' / job_id / f'{rule_id}-{fingerprint}.json'
            output = await assess(candidate, related, pages, settings['model'], path, job_id)
            async with sessions.begin() as session:
                run = await session.get(AnalysisRun, run_id, with_for_update=True)
                if not run or run.status != 'complete':
                    return
                data = deepcopy(run.payload)
                job = data.get('assessment_job') or {}
                if job.get('id') != job_id or job.get('status') == 'cancelled':
                    return
                current = next((r for r in data['rules'] if r['id'] == rule_id), None)
                fresh = current and assessment_fingerprint(current, related_rules(current, duplicate_index(data['rules']))) == fingerprint
                if fresh:
                    current['assessment'] = output.model_dump(mode='json')
                    job['assessed'] += 1
                    session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor='Jev assessment', action='rule_assessed',
                        payload={'rule_id': rule_id, 'revision': current['revision'], 'job_id': job_id,
                                 'requested_by': settings['actor'], 'outcome': output.outcome,
                                 'model': output.model, 'prompt_version': output.prompt_version, 'fingerprint': fingerprint}))
                else:
                    job['skipped'] += 1
                job['pending'].pop(0)
                job['processed'] += 1
                run.payload, run.version = data, run.version + 1
    except Exception as exc:
        async with sessions.begin() as session:
            run = await session.get(AnalysisRun, run_id, with_for_update=True)
            if not run or run.status != 'complete' or (run.payload.get('assessment_job') or {}).get('id') != job_id:
                return
            data = deepcopy(run.payload)
            if data['assessment_job'].get('status') == 'cancelled':
                return
            message = str(exc) if isinstance(exc, ProviderFailure) else 'Assessment stopped unexpectedly. Completed assessments are saved.'
            data['assessment_job'].update(status='failed', error=message, failed_rule_id=rule_id)
            run.payload, run.version = data, run.version + 1
        logger.error('Assessment stopped: run_id=%s job_id=%s rule_id=%s error_type=%s', run_id, job_id, rule_id, type(exc).__name__)
        raise RuntimeError(f'Assessment {job_id} stopped. See its saved error.') from None
