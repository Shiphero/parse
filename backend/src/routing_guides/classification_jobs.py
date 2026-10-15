"""Resumable classification of existing drafts without overwriting review decisions."""
from copy import deepcopy
from hashlib import sha256
import json
from datetime import datetime, timezone
from uuid import uuid4

from routing_guides.classification_provider import classify, PROMPT_VERSION
from routing_guides.analysis_provider import ProviderFailure
from routing_guides.db import sessions
from routing_guides.models import AnalysisRun, AuditEvent
from routing_guides.storage import guide_directory
from routing_guides.classification_mapping import apply_classification, needs_auto_classification
from routing_guides.rules import RuleSpec


async def run_classification(run_id, job_id):
    try:
        while True:
            async with sessions.begin() as session:
                run = await session.get(AnalysisRun, run_id, with_for_update=True)
                job = (run.payload.get('classification_job') or {}) if run else {}
                if not run or run.status != 'complete' or job.get('id') != job_id or job.get('status') in {'complete', 'cancelled'}:
                    return
                data = deepcopy(run.payload)
                job = data['classification_job']
                if not job['pending']:
                    job['status'] = 'complete'
                    run.payload, run.version = data, run.version + 1
                    return
                job['status'], job['error'] = 'running', None
                batch = job['pending'][:job.get('batch_size', 20)]
                current = {r['id']: r for r in data['rules']}
                requested = [deepcopy(current[item['id']]) for item in batch if item['id'] in current
                             and current[item['id']]['revision'] == item['revision']
                             and current[item['id']]['status'] == item.get('status', current[item['id']]['status'])
                             and current[item['id']].get('review') == item.get('review', current[item['id']].get('review'))
                             and current[item['id']]['status'] in (['pending', 'approved'] if job.get('include_approved') else ['pending'])
                             and needs_auto_classification(current[item['id']]['spec'])]
                settings = deepcopy(job)
                guide_id = run.guide_id
                run.payload = data
            output = None
            if requested:
                fingerprint = sha256(json.dumps([(r['id'], r['revision']) for r in requested]).encode()).hexdigest()[:20]
                path = guide_directory(guide_id) / 'classification' / job_id / f'batch-{settings["processed"]}-{fingerprint}.json'
                try:
                    output = await classify(settings['provider'], settings['model'], requested, path)
                except ProviderFailure as exc:
                    if not exc.split or len(requested) <= 1:
                        raise
                    async with sessions.begin() as session:
                        run = await session.get(AnalysisRun, run_id, with_for_update=True)
                        data = deepcopy(run.payload)
                        job = data.get('classification_job', {})
                        if run.status != 'complete' or job.get('id') != job_id or job.get('status') == 'cancelled':
                            return
                        job['batch_size'] = max(1, len(requested) // 2)
                        run.payload, run.version = data, run.version + 1
                    continue
            async with sessions.begin() as session:
                run = await session.get(AnalysisRun, run_id, with_for_update=True)
                data = deepcopy(run.payload)
                job = data.get('classification_job', {})
                if run.status != 'complete' or job.get('id') != job_id or job.get('status') == 'cancelled':
                    return
                expected = {item['id']: item['revision'] for item in batch}
                requested_by_id = {item['id']: item for item in requested}
                current = {r['id']: r for r in data['rules']}
                applied = 0
                for classified in output.rules if output else []:
                    rule = current.get(str(classified.id))
                    # Recheck revisions AFTER the model call: human edits always win.
                    if not rule or rule['status'] not in (['pending', 'approved'] if settings.get('include_approved') else ['pending']) or rule['revision'] != expected[rule['id']] or not needs_auto_classification(rule['spec']):
                        continue
                    original = requested_by_id[rule['id']]
                    if rule['status'] != original['status'] or rule.get('review') != original.get('review'):
                        continue
                    before = deepcopy(rule)
                    rule['spec'], reason = apply_classification(rule['spec'], classified)
                    if rule['spec'] != RuleSpec.model_validate(before['spec']).model_dump(mode='json'):
                        rule.update(revision=rule['revision']+1, status='pending', review=None,
                                    carried_from_release_id=None, carried_from_rule_id=None)
                    rule.update(classification={'method': 'ai', 'reason': reason, 'provider': settings['provider'],
                                                'model': output.model, 'prompt_version': PROMPT_VERSION,
                                                'at': datetime.now(timezone.utc).isoformat()})
                    session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor='AI classifier', action='rule_auto_classified',
                                         payload={'before': before, 'after': deepcopy(rule), 'job_id': job_id, 'requested_by': settings['actor']}))
                    applied += 1
                job['pending'] = job['pending'][len(batch):]
                job['processed'] += len(batch)
                job['applied'] += applied
                job['skipped'] += len(batch) - applied
                if output:
                    job['batches'].append({'model': output.model, 'usage': output.usage, 'applied': applied})
                run.payload, run.version = data, run.version + 1
    except Exception as exc:
        async with sessions.begin() as session:
            run = await session.get(AnalysisRun, run_id, with_for_update=True)
            if run and (run.payload.get('classification_job') or {}).get('id') == job_id:
                data = deepcopy(run.payload)
                if data['classification_job'].get('status') != 'cancelled':
                    data['classification_job'].update(status='failed', error=str(exc) if isinstance(exc, ProviderFailure) else 'Classification stopped unexpectedly. Completed batches are saved.')
                    run.payload, run.version = data, run.version + 1
