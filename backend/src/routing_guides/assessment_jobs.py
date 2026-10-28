"""Prepare and check pending definitions, then apply enabled automatic draft decisions."""
from copy import deepcopy
import logging
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from routing_guides.analysis_provider import ProviderFailure
from routing_guides.assessment import PROMPT_VERSION, assessment_fingerprint, related_rules, duplicate_index, new_assessment_job
from routing_guides.assessment_provider import assess, AssessmentResponseError, failed_assessment
from routing_guides.connections import connection
from routing_guides.db import sessions
from routing_guides.models import AnalysisRun, AuditEvent, GuidePage
from routing_guides.storage import guide_directory
from routing_guides.tasks import assess_guide_rules
from routing_guides.resolution_jobs import enable_resolution, prepare_next
from routing_guides.resolution import RESOLUTION_VERSION
from routing_guides.review_processing import REVIEW_CONCURRENCY, completed_batch, now, resolution_context

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
    try:
        await enable_resolution(job, run.config)
    except ValueError as exc:
        job.update(status='failed', reason='configuration_required', error=str(exc))
        return
    # Procrastinate uses the existing psycopg connection without committing it.
    sql_connection = await session.connection()
    raw_connection = await sql_connection.get_raw_connection()
    await assess_guide_rules.configure(connection=raw_connection.driver_connection,
        lock=f'assessment:{run.id}', queueing_lock=f'assessment:{run.id}').defer_async(
            run_id=str(run.id), job_id=job['id'])


async def run_assessment(run_id: UUID, job_id: str):
    rule_id = None
    source_cache = {}
    try:
        # Do not silently change the contract of a job resumed after deployment.
        async with sessions.begin() as session:
            run = await session.get(AnalysisRun, run_id, with_for_update=True)
            job = (run.payload.get('assessment_job') or {}) if run else {}
            if not run or run.status != 'complete' or job.get('id') != job_id or job.get('status') in {'complete', 'cancelled'}:
                return
            if (job.get('prompt_version') != PROMPT_VERSION
                    or job.get('resolution_version', RESOLUTION_VERSION) != RESOLUTION_VERSION):
                data = deepcopy(run.payload)
                data['assessment_job'].update(status='failed', reason='version_changed',
                    error='Automatic review has been updated. Start a new run to check the remaining rules. Completed work is saved.')
                run.payload, run.version = data, run.version + 1
                return
        while True:
            if await prepare_next(sessions, run_id, job_id, source_cache):
                continue
            if not await check_next(run_id, job_id, source_cache):
                return
    except Exception as exc:
        async with sessions.begin() as session:
            run = await session.get(AnalysisRun, run_id, with_for_update=True)
            if not run or run.status != 'complete' or (run.payload.get('assessment_job') or {}).get('id') != job_id:
                return
            data = deepcopy(run.payload)
            if data['assessment_job'].get('status') == 'cancelled':
                return
            message = str(exc) if isinstance(exc, ProviderFailure) else 'Assessment stopped unexpectedly. Completed assessments are saved.'
            data['assessment_job'].update(status='failed', error=message, failed_rule_id=rule_id, updated_at=now())
            if isinstance(exc, ProviderFailure) and exc.code:
                data['assessment_job']['reason'] = exc.code
            run.payload, run.version = data, run.version + 1
        logger.error('Assessment stopped: run_id=%s job_id=%s rule_id=%s error_type=%s', run_id, job_id, rule_id, type(exc).__name__)
        raise RuntimeError(f'Assessment {job_id} stopped. See its saved error.') from None


async def check_next(run_id, job_id, source_cache):
    work = []
    async with sessions.begin() as session:
        run = await session.get(AnalysisRun, run_id, with_for_update=True)
        job = (run.payload.get('assessment_job') or {}) if run else {}
        if not run or run.status != 'complete' or job.get('id') != job_id or job.get('status') in {'complete', 'cancelled'}:
            return False
        data = deepcopy(run.payload)
        job = data['assessment_job']
        index = duplicate_index(data['rules'])
        by_id = {r['id']: r for r in data['rules']}
        for item in list(job['pending']):
            candidate = by_id.get(item['id'])
            if not candidate or candidate['status'] != 'pending' or candidate['revision'] != item['revision']:
                job['pending'].remove(item)
                job['processed'] += 1
                job['skipped'] += 1
                continue
            related = deepcopy(related_rules(candidate, index))
            fingerprint = assessment_fingerprint(candidate, related)
            previous = candidate.get('assessment') or {}
            if (not previous.get('check_failed') and previous.get('fingerprint') == fingerprint
                    and previous.get('prompt_version') == PROMPT_VERSION and previous.get('model') == job['model']
                    and previous.get('resolution_fingerprint') == resolution_context(candidate)):
                previous_job = previous.get('job_id')
                previous['job_id'] = job_id
                job['pending'].remove(item)
                job['processed'] += 1
                job['assessed'] += 1
                job['reused_assessments'] = job.get('reused_assessments', 0) + 1
                session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor='Automatic review', action='rule_assessment_reused',
                    payload={'rule_id': candidate['id'], 'revision': candidate['revision'], 'job_id': job_id,
                             'previous_job_id': previous_job, 'fingerprint': fingerprint}))
                continue
            candidate = deepcopy(candidate)
            source_id = candidate.get('source_guide_id') or str(run.guide_id)
            if source_id not in source_cache:
                rows = (await session.execute(select(GuidePage.page_index, GuidePage.text).where(
                    GuidePage.guide_id == UUID(source_id)))).all()
                source_cache[source_id] = {p.page_index + 1: p.text for p in rows}
            if (candidate.get('resolution') or {}).get('revision') != candidate['revision']:
                candidate.pop('resolution', None)
            resolution = candidate.get('resolution') or {}
            references = [*candidate['spec']['evidence'],
                *(source for entry in [*resolution.get('changes', []), *resolution.get('questions', [])]
                  for source in entry.get('sources', []))]
            numbers = {n for e in references for n in (e['page'] - 1, e['page'], e['page'] + 1) if n > 0}
            pages = {n: source_cache[source_id][n] for n in numbers if n in source_cache[source_id]}
            work.append({'candidate': candidate, 'related': related, 'pages': pages, 'fingerprint': fingerprint})
            if len(work) == REVIEW_CONCURRENCY:
                break
        if not job['pending']:
            from routing_guides.automatic_review import approve_completed_rules, set_aside_non_rules
            await set_aside_non_rules(session, run, data, source_cache)
            await approve_completed_rules(session, run, data, source_cache)
            job.update(status='complete', updated_at=now(), completed_at=now())
            run.payload, run.version = data, run.version + 1
            return False
        job.update(status='running', error=None, updated_at=now())
        settings, guide_id = deepcopy(job), run.guide_id
        run.payload, run.version = data, run.version + 1

    async def evaluate(item):
        candidate, related, pages = item['candidate'], item['related'], item['pages']
        path = guide_directory(guide_id) / 'assessment' / job_id / f'{candidate["id"]}-{item["fingerprint"]}.json'
        # A failed repair must not hide a successful inclusion assessment. A pure
        # heading can be set aside without inventing a catalog mapping for it.
        try:
            output = await assess(candidate, related, pages, settings['model'], path, job_id)
        except AssessmentResponseError:
            output = failed_assessment(candidate, related, pages, settings['model'], job_id)
            logger.warning('Assessment response rejected: run_id=%s job_id=%s rule_id=%s', run_id, job_id, candidate['id'])
        output.resolution_fingerprint = resolution_context(candidate)
        return output

    fatal = None
    async with completed_batch(work, evaluate) as results:
        async for item, output, error in results:
            if error:
                fatal = fatal or error
                continue
            rule_id, fingerprint = item['candidate']['id'], item['fingerprint']
            async with sessions.begin() as session:
                run = await session.get(AnalysisRun, run_id, with_for_update=True)
                if not run or run.status != 'complete':
                    return False
                data = deepcopy(run.payload)
                job = data.get('assessment_job') or {}
                if job.get('id') != job_id or job.get('status') == 'cancelled':
                    return False
                selected = next((r for r in job['pending'] if r['id'] == rule_id), None)
                if selected is None:
                    continue
                current = next((r for r in data['rules'] if r['id'] == rule_id), None)
                fresh = (current and assessment_fingerprint(current, related_rules(current, duplicate_index(data['rules']))) == fingerprint
                         and resolution_context(current) == output.resolution_fingerprint)
                if fresh:
                    current['assessment'] = output.model_dump(mode='json')
                    counter = 'failed' if output.check_failed else 'assessed'
                    job[counter] = job.get(counter, 0) + 1
                    session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor='Automatic review',
                        action='rule_assessment_failed' if output.check_failed else 'rule_assessed',
                        payload={'rule_id': rule_id, 'revision': current['revision'], 'job_id': job_id,
                                 'requested_by': settings['actor'], 'outcome': output.outcome, 'check_failed': output.check_failed,
                                 'model': output.model, 'prompt_version': output.prompt_version, 'fingerprint': fingerprint}))
                else:
                    job['skipped'] += 1
                job['pending'].remove(selected)
                job['processed'] += 1
                job['updated_at'] = now()
                run.payload, run.version = data, run.version + 1
    if fatal:
        raise fatal
    return True
