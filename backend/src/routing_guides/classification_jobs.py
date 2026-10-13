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
from routing_guides.taxonomy import needs_classification
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
                batch = job['pending'][:40]
                current = {r['id']: r for r in data['rules']}
                requested = [deepcopy(current[item['id']]) for item in batch if item['id'] in current
                             and current[item['id']]['revision'] == item['revision']
                             and current[item['id']]['status'] == 'pending'
                             and needs_classification(current[item['id']]['spec'])]
                settings = deepcopy(job)
                guide_id = run.guide_id
                run.payload = data
            output = None
            if requested:
                fingerprint = sha256(json.dumps([(r['id'], r['revision']) for r in requested]).encode()).hexdigest()[:20]
                path = guide_directory(guide_id) / 'classification' / job_id / f'batch-{settings["processed"]}-{fingerprint}.json'
                output = await classify(settings['provider'], settings['model'], requested, path)
            async with sessions.begin() as session:
                run = await session.get(AnalysisRun, run_id, with_for_update=True)
                data = deepcopy(run.payload)
                job = data.get('classification_job', {})
                if run.status != 'complete' or job.get('id') != job_id or job.get('status') == 'cancelled':
                    return
                expected = {item['id']: item['revision'] for item in batch}
                current = {r['id']: r for r in data['rules']}
                applied = 0
                for classified in output.rules if output else []:
                    rule = current.get(str(classified.id))
                    # Recheck revisions AFTER the model call: human edits always win.
                    if not rule or rule['status'] != 'pending' or rule['revision'] != expected[rule['id']] or not needs_classification(rule['spec']):
                        continue
                    before = deepcopy(rule)
                    spec = rule['spec']
                    if spec.get('purpose', 'unclassified') == 'unclassified':
                        spec['purpose'] = classified.purpose
                    if spec.get('operational_category', 'unclassified') == 'unclassified':
                        spec['operational_category'] = classified.operational_category
                    if not spec.get('consumption_points'):
                        spec['consumption_points'] = classified.consumption_points
                    if spec.get('schema_version') != '1.2':
                        spec['schema_version'] = '1.1'
                    elif spec['purpose'] == 'shipment_validation' and not spec.get('standard_check'):
                        spec.update(verification='unresolved', assertion=None)
                    rule['spec'] = RuleSpec.model_validate(spec).model_dump(mode='json')
                    rule.update(revision=rule['revision']+1, review=None, carried_from_release_id=None, carried_from_rule_id=None,
                                classification={'method': 'ai', 'reason': classified.reason, 'provider': settings['provider'],
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
