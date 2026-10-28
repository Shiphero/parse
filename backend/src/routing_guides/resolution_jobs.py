"""First pass over all selected rules, before any final duplicate/readiness assessment."""
from copy import deepcopy
import asyncio
import logging
from uuid import UUID, uuid4

from sqlalchemy import select
from routing_guides.analysis_provider import ProviderFailure
from routing_guides.assessment_provider import AssessmentResponseError
from routing_guides.connections import connection
from routing_guides.models import AnalysisRun, AuditEvent, GuidePage
from routing_guides.resolution import ResolutionRecord, ResolutionPlan, RESOLUTION_VERSION, resolve_plan, preparation_targets
from routing_guides.resolution_provider import propose, verify_changes, select_source_pages
from routing_guides.storage import guide_directory
from routing_guides.review_processing import (REVIEW_CONCURRENCY, completed_batch, now,
    preparation_fingerprint, reusable_preparation, resolution_context)

logger = logging.getLogger(__name__)


async def enable_resolution(job: dict, run_config: dict) -> None:
    provider = run_config.get('provider')
    if provider not in {'anthropic', 'openai', 'litellm'}:
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
    job.update(reused_prepared=0, prepared_without_model=0, preparation_failures={}, recent_preparation_failures=[],
               concurrency=REVIEW_CONCURRENCY, processing_version=2)


def preserve_assessment_context(candidate, before):
    assessment = candidate.get('assessment')
    if not assessment:
        return
    if resolution_context(before) == resolution_context(candidate):
        assessment['resolution_fingerprint'] = resolution_context(candidate)
    else:
        candidate.pop('assessment', None)


async def prepare_next(sessions, run_id, job_id: str, source_cache: dict) -> bool:
    """Snapshot pending preparation, refill bounded slots, and checkpoint each result."""
    work = []
    async with sessions.begin() as session:
        run = await session.get(AnalysisRun, run_id, with_for_update=True)
        job = (run.payload.get('assessment_job') or {}) if run else {}
        if (not run or run.status != 'complete' or job.get('id') != job_id
                or job.get('status') in {'complete', 'cancelled'} or job.get('phase') != 'resolve'):
            return False
        data = deepcopy(run.payload)
        job = data['assessment_job']
        by_id = {r['id']: r for r in data['rules']}
        for offset, item in enumerate(list(job['preparing'])):
            if offset % 16 == 0:
                # Large drafts must not starve the worker heartbeat while their
                # inexpensive eligibility checks are collected.
                await asyncio.sleep(0)
            current = by_id.get(item['id'])
            if not current or current['status'] != 'pending' or current['revision'] != item['revision']:
                job['preparing'].remove(item)
                job['prepared'] += 1
                continue
            if reusable_preparation(current, job):
                before = deepcopy(current)
                current['resolution'].update(job_id=job_id, verifier_model=job['model'],
                    output_fingerprint=preparation_fingerprint(current))
                preserve_assessment_context(current, before)
                job['preparing'].remove(item)
                job['prepared'] += 1
                job['reused_prepared'] = job.get('reused_prepared', 0) + 1
                continue
            if not preparation_targets(current):
                before = deepcopy(current)
                fingerprint = preparation_fingerprint(current)
                _, record = resolve_plan(current, ResolutionPlan(proposed_spec=None), {}, {},
                    job['resolution_provider'], job['resolution_model'], fingerprint)
                record.job_id, record.verifier_model, record.output_fingerprint = job_id, job['model'], fingerprint
                current['resolution'] = record.model_dump(mode='json')
                preserve_assessment_context(current, before)
                job['preparing'].remove(item)
                job['prepared'] += 1
                job['prepared_without_model'] = job.get('prepared_without_model', 0) + 1
                session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor='Automatic review',
                    action='rule_preparation_not_needed', payload={'rule_id': current['id'],
                        'revision': current['revision'], 'job_id': job_id}))
                continue
            candidate = deepcopy(current)
            source_id = candidate.get('source_guide_id') or str(run.guide_id)
            if source_id not in source_cache:
                rows = (await session.execute(select(GuidePage.page_index, GuidePage.text).where(
                    GuidePage.guide_id == UUID(source_id)))).all()
                source_cache[source_id] = {row.page_index + 1: row.text for row in rows}
            work.append({'candidate': candidate,
                         'fingerprint': preparation_fingerprint(candidate), 'source_id': source_id})
        if not job['preparing']:
            if job.get('auto_process'):
                from routing_guides.automatic_review import remove_exact_duplicates
                await remove_exact_duplicates(session, run, data, source_cache)
            job['phase'] = 'assess'
        job.update(status='running', error=None, updated_at=now())
        settings, guide_id = deepcopy(job), run.guide_id
        run.payload, run.version = data, run.version + 1

    async def prepare(item):
        candidate, fingerprint = item['candidate'], item['fingerprint']
        # Rank pages only when a processing slot opens, outside the row lock and
        # event loop. Never scan the entire guide for every queued rule up front.
        pages = await asyncio.to_thread(select_source_pages, candidate, source_cache[item['source_id']])
        root = guide_directory(guide_id) / 'assessment' / job_id / 'resolution'
        path = root / f'{candidate["id"]}-{fingerprint}.json'
        try:
            plan = await propose(candidate, pages, settings['resolution_provider'], settings['resolution_model'], path,
                                 settings['model'])
            verdicts = await verify_changes(candidate, plan, pages, settings['model'], path.with_suffix('.verification.json'))
            spec, record = resolve_plan(candidate, plan, verdicts, pages, settings['resolution_provider'],
                                        settings['resolution_model'], fingerprint)
        except AssessmentResponseError as error:
            spec = candidate['spec']
            code = getattr(error, 'code', 'verification_response_invalid')
            fields = getattr(error, 'fields', [])
            message = str(error) if hasattr(error, 'code') else 'The correction could not be independently verified. Retry automatic preparation; the original rule is unchanged.'
            record = ResolutionRecord(revision=candidate['revision'], input_fingerprint=fingerprint,
                provider=settings['resolution_provider'], model=settings['resolution_model'], at=now(),
                failed=True, failure_code=code, failure_message=message, validation_fields=fields)
            logger.warning('Rule preparation rejected: run_id=%s job_id=%s rule_id=%s code=%s fields=%s',
                           run_id, job_id, candidate['id'], code, ','.join(fields))
        record.job_id, record.verifier_model = job_id, settings['model']
        return spec, record

    fatal = None
    async with completed_batch(work, prepare, keep_running=lambda: fatal is None) as results:
        async for item, output, error in results:
            if error:
                fatal = fatal or error
                continue
            candidate, fingerprint = item['candidate'], item['fingerprint']
            spec, record = output
            async with sessions.begin() as session:
                run = await session.get(AnalysisRun, run_id, with_for_update=True)
                if not run or run.status != 'complete':
                    return True
                data = deepcopy(run.payload)
                job = data.get('assessment_job') or {}
                if job.get('id') != job_id or job.get('status') == 'cancelled':
                    return True
                selected = next((r for r in job['preparing'] if r['id'] == candidate['id']), None)
                if selected is None:
                    continue
                current = next((r for r in data['rules'] if r['id'] == candidate['id']), None)
                if current and preparation_fingerprint(current) == fingerprint:
                    before = deepcopy(current)
                    if any(c.applied for c in record.changes):
                        current.update(spec=spec, revision=current['revision'] + 1, review=None,
                                       carried_from_release_id=None, carried_from_rule_id=None)
                        from routing_guides.analysis_jobs import evidence_issues
                        from routing_guides.rules import RuleSpec
                        current['evidence_issues'] = evidence_issues(RuleSpec.model_validate(spec), source_cache[item['source_id']])
                        for pending in [*job['pending'], *job.get('selected_revisions', [])]:
                            if pending['id'] == current['id']:
                                pending['revision'] = current['revision']
                        job['updated'] += 1
                    record.output_fingerprint = preparation_fingerprint(current)
                    current['resolution'] = record.model_dump(mode='json')
                    preserve_assessment_context(current, before)
                    job['resolution_failed'] += int(record.failed)
                    recent = job.setdefault('recent_preparation_failures', [])
                    recent.append(record.failed)
                    job['recent_preparation_failures'] = recent[-10:]
                    if record.failed:
                        failures = job.setdefault('preparation_failures', {})
                        failures[record.failure_code] = failures.get(record.failure_code, 0) + 1
                    session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor='Automatic rule preparation',
                        action='rule_auto_resolved' if any(c.applied for c in record.changes) else 'rule_resolution_checked',
                        payload={'before': before, 'after': deepcopy(current), 'job_id': job_id, 'requested_by': settings['actor']}))
                    if len(recent) >= 10 and all(recent[-10:]):
                        job['reason'] = 'repeated_invalid_responses'
                        fatal = fatal or ProviderFailure('Automatic preparation stopped after repeated unusable responses. Completed work is saved. Contact your administrator before retrying.')
                job['preparing'].remove(selected)
                job['prepared'] += 1
                job['updated_at'] = now()
                from routing_guides.automatic_review import restore_changed_duplicates
                restore_changed_duplicates(session, run, data)
                run.payload, run.version = data, run.version + 1
    if fatal:
        raise fatal
    return True
