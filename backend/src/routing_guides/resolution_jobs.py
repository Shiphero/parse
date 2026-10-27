"""First pass over all selected rules, before any final duplicate/readiness assessment."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from routing_guides.assessment import assessment_fingerprint, related_rules, duplicate_index
from routing_guides.assessment_provider import AssessmentResponseError
from routing_guides.connections import connection
from routing_guides.models import AnalysisRun, AuditEvent, GuidePage
from routing_guides.resolution import ResolutionRecord, RESOLUTION_VERSION, resolve_plan
from routing_guides.resolution_provider import propose, verify_changes, select_source_pages
from routing_guides.storage import guide_directory


async def enable_resolution(job: dict, run_config: dict) -> None:
    provider = run_config.get('provider')
    if provider not in {'anthropic', 'openai'}:
        provider = 'anthropic'
    config = await connection(provider)
    model = run_config.get('model') if run_config.get('provider') == provider else config['model']
    if not config['key'] or not model:
        raise ValueError('Set up the analysis provider and model in Connections to resolve rules automatically.')
    job.update(phase='resolve', resolution_version=RESOLUTION_VERSION,
               resolution_provider=provider, resolution_model=model,
               preparing=deepcopy(job['pending']), prepared=0, updated=0, resolution_failed=0)
    job.setdefault('auto_process', True)
    job['selected_revisions'] = deepcopy(job['pending'])


async def prepare_next(sessions, run_id, job_id: str, source_cache: dict) -> bool:
    """Return True when the resolution phase consumed work or advanced its checkpoint."""
    async with sessions.begin() as session:
        run = await session.get(AnalysisRun, run_id, with_for_update=True)
        job = (run.payload.get('assessment_job') or {}) if run else {}
        if (not run or run.status != 'complete' or job.get('id') != job_id
                or job.get('status') in {'complete', 'cancelled'} or job.get('phase') != 'resolve'):
            return False
        data = deepcopy(run.payload)
        job = data['assessment_job']
        if not job['preparing']:
            if job.get('auto_process'):
                from routing_guides.automatic_review import remove_exact_duplicates
                await remove_exact_duplicates(session, run, data, source_cache)
            job['phase'] = 'assess'
            run.payload, run.version = data, run.version + 1
            return True
        item = job['preparing'][0]
        current = next((r for r in data['rules'] if r['id'] == item['id']), None)
        if not current or current['status'] != 'pending' or current['revision'] != item['revision']:
            job['preparing'].pop(0)
            job['prepared'] += 1
            run.payload, run.version = data, run.version + 1
            return True
        candidate = deepcopy(current)
        related = related_rules(candidate, duplicate_index(data['rules']))
        fingerprint = assessment_fingerprint(candidate, related)
        source_id = candidate.get('source_guide_id') or str(run.guide_id)
        if source_id not in source_cache:
            rows = (await session.execute(select(GuidePage.page_index, GuidePage.text).where(GuidePage.guide_id == UUID(source_id)))).all()
            source_cache[source_id] = {row.page_index + 1: row.text for row in rows}
        pages = select_source_pages(candidate, source_cache[source_id])
        settings = deepcopy(job)
        guide_id = run.guide_id
        job.update(status='running', error=None)
        run.payload = data
    root = guide_directory(guide_id) / 'assessment' / job_id / 'resolution'
    path = root / f'{candidate["id"]}-{fingerprint}.json'
    try:
        plan = await propose(candidate, pages, settings['resolution_provider'], settings['resolution_model'], path)
        verdicts = await verify_changes(candidate, plan, pages, settings['model'], path.with_suffix('.verification.json'))
        spec, record = resolve_plan(candidate, plan, verdicts, pages, settings['resolution_provider'],
                                    settings['resolution_model'], fingerprint)
    except AssessmentResponseError:
        spec = candidate['spec']
        record = ResolutionRecord(revision=candidate['revision'], input_fingerprint=fingerprint,
            provider=settings['resolution_provider'], model=settings['resolution_model'],
            at=datetime.now(timezone.utc).isoformat(), failed=True)
    async with sessions.begin() as session:
        run = await session.get(AnalysisRun, run_id, with_for_update=True)
        if not run or run.status != 'complete':
            return True
        data = deepcopy(run.payload)
        job = data.get('assessment_job') or {}
        if job.get('id') != job_id or job.get('status') == 'cancelled':
            return True
        current = next((r for r in data['rules'] if r['id'] == candidate['id']), None)
        if current and assessment_fingerprint(current, related_rules(current, duplicate_index(data['rules']))) == fingerprint:
            before = deepcopy(current)
            if any(c.applied for c in record.changes):
                current.update(spec=spec, revision=current['revision'] + 1, review=None,
                               carried_from_release_id=None, carried_from_rule_id=None)
                from routing_guides.analysis_jobs import evidence_issues
                from routing_guides.rules import RuleSpec
                current['evidence_issues'] = evidence_issues(RuleSpec.model_validate(spec), source_cache[source_id])
                for pending in job['pending']:
                    if pending['id'] == current['id']:
                        pending['revision'] = current['revision']
                for selected in job.get('selected_revisions', []):
                    if selected['id'] == current['id']:
                        selected['revision'] = current['revision']
                job['updated'] += 1
            current['resolution'] = record.model_dump(mode='json')
            current.pop('assessment', None)
            job['resolution_failed'] += int(record.failed)
            session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor='Automatic rule preparation',
                action='rule_auto_resolved' if any(c.applied for c in record.changes) else 'rule_resolution_checked',
                payload={'before': before, 'after': deepcopy(current), 'job_id': job_id, 'requested_by': settings['actor']}))
        job['preparing'].pop(0)
        job['prepared'] += 1
        from routing_guides.automatic_review import restore_changed_duplicates
        restore_changed_duplicates(session, run, data)
        run.payload, run.version = data, run.version + 1
    return True
