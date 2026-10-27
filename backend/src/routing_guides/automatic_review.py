"""Audited automatic decisions on current pending drafts, never published releases."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from routing_guides.assessment import PROMPT_VERSION, assessment_fingerprint, duplicate_index, related_rules, local_issues
from routing_guides.models import AuditEvent, GuidePage
from routing_guides.rules import RuleSpec

ACTOR = 'Automatic review'


async def source_pages(session, rule, cache):
    source_id = rule['source_guide_id']
    if source_id not in cache:
        rows = (await session.execute(select(GuidePage.page_index, GuidePage.text).where(
            GuidePage.guide_id == UUID(source_id)))).all()
        cache[source_id] = {row.page_index + 1: row.text for row in rows}
    return cache[source_id]


def definition_key(rule):
    value = RuleSpec.model_validate(rule['spec']).model_dump(mode='json')
    value['evidence'] = sorted({e['quote'].strip() for e in value['evidence']})
    return json.dumps([rule['source_guide_id'], value], sort_keys=True)


def duplicate_key(rule, pages):
    from routing_guides.analysis_jobs import evidence_issues
    spec = RuleSpec.model_validate(rule['spec'])
    if (rule.get('evidence_issues') or spec.unresolved_questions or evidence_issues(spec, pages)
            or any(e.kind != 'text' or e.region is not None for e in spec.evidence)):
        return None
    # Do not merge paraphrases, different workflow settings, scopes or check parameters.
    # Keep all originals; only page movement of identical quotations is immaterial here.
    return definition_key(rule)


def restore_changed_duplicates(session, run, data):
    by_id = {r['id']: r for r in data['rules']}
    for rule in data['rules']:
        review = rule.get('review') or {}
        if rule['status'] != 'ignored' or review.get('mode') != 'automatic_duplicate':
            continue
        keeper = by_id.get(review.get('duplicate_of'))
        if keeper and keeper['status'] in {'pending', 'approved'} and definition_key(keeper) == definition_key(rule):
            continue
        before = deepcopy(rule)
        rule.update(status='pending', review={'actor': ACTOR, 'mode': 'duplicate_reopened',
            'revision': rule['revision'], 'at': datetime.now(timezone.utc).isoformat(),
            'note': 'The retained requirement changed or was excluded. This original is back in review.'})
        rule.pop('assessment', None)
        session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor=ACTOR, action='duplicate_reopened',
            payload={'before': before, 'after': deepcopy(rule)}))


async def remove_exact_duplicates(session, run, data, cache):
    restore_changed_duplicates(session, run, data)
    job = data['assessment_job']
    selected = {r['id']: r['revision'] for r in job.get('selected_revisions', [])}
    keepers = {}
    removed = set()
    # Prefer an existing approved rule, then stable draft order.
    ordered = sorted(data['rules'], key=lambda r: r['status'] != 'approved')
    for rule in ordered:
        if rule['status'] not in {'pending', 'approved'}:
            continue
        key = duplicate_key(rule, await source_pages(session, rule, cache))
        if key is None:
            continue
        keeper = keepers.setdefault(key, rule)
        if (keeper is rule or rule['status'] != 'pending' or rule.get('review') or rule.get('automation_hold')
                or selected.get(rule['id']) != rule['revision']):
            continue
        before = deepcopy(rule)
        rule.update(status='ignored', review={'actor': ACTOR, 'mode': 'automatic_duplicate',
            'revision': rule['revision'], 'at': datetime.now(timezone.utc).isoformat(),
            'note': 'Identical requirement already retained in this draft. Original text and evidence remain available.',
            'duplicate_of': keeper['id'], 'job_id': job['id'], 'requested_by': job['actor']})
        removed.add(rule['id'])
        session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor=ACTOR, action='rule_duplicate_removed',
            payload={'before': before, 'after': deepcopy(rule), 'kept_rule_id': keeper['id'], 'job_id': job['id']}))
    job['duplicates_removed'] = job.get('duplicates_removed', 0) + len(removed)
    job['pending'] = [r for r in job['pending'] if r['id'] not in removed]
    job['processed'] += len(removed)


async def approve_completed_rules(session, run, data, cache):
    from routing_guides.assessment_provider import DIMENSIONS
    job = data['assessment_job']
    if not job.get('auto_process'):
        return
    selected = {r['id']: r['revision'] for r in job.get('selected_revisions', [])}
    index = duplicate_index(data['rules'])
    fresh = {}
    approved = []
    for rule in data['rules']:
        assessment = rule.get('assessment') or {}
        related = related_rules(rule, index)
        fingerprint = assessment_fingerprint(rule, related)
        if assessment.get('prompt_version') == PROMPT_VERSION and assessment.get('fingerprint') == fingerprint:
            fresh[rule['id']] = fingerprint
        resolution = rule.get('resolution') or {}
        if (rule['status'] != 'pending' or rule.get('review') or rule.get('automation_hold') or selected.get(rule['id']) != rule['revision']
                or rule['id'] not in fresh or assessment.get('job_id') != job['id']
                or assessment.get('outcome') != 'ready' or assessment.get('check_failed')
                or not assessment.get('auto_approval_supported') or assessment.get('issues')
                or resolution.get('revision') != rule['revision'] or resolution.get('failed')
                or resolution.get('questions') or any(not c['applied'] for c in resolution.get('changes', []))):
            continue
        if ({d['name'] for d in assessment.get('dimensions', [])} != set(DIMENSIONS)
                or any(d['choice'] != 'supported' for d in assessment['dimensions'])
                or {d['rule_id'] for d in assessment.get('duplicates', [])} != {r['id'] for r in related}
                or any(d['choice'] != 'distinct' for d in assessment.get('duplicates', []))):
            continue
        # Revalidate actual source text and deterministic blockers at the decision boundary.
        if local_issues(rule, related, await source_pages(session, rule, cache)):
            continue
        approved.append((rule, deepcopy(rule)))
    for rule, before in approved:
        rule.update(status='approved', review={'actor': ACTOR, 'mode': 'automatic',
            'revision': rule['revision'], 'at': datetime.now(timezone.utc).isoformat(),
            'note': 'Source and duplicate checks passed. Approved automatically in the draft.',
            'job_id': job['id'], 'requested_by': job['actor'], 'assessment_fingerprint': fresh[rule['id']]})
    # Only decision metadata changed. Preserve fresh checks without invalidating peers
    # solely because these verified rules moved from pending to approved.
    if approved:
        index = duplicate_index(data['rules'])
        for rule in data['rules']:
            if rule['id'] in fresh:
                rule['assessment']['fingerprint'] = assessment_fingerprint(rule, related_rules(rule, index))
        for rule, before in approved:
            session.add(AuditEvent(id=uuid4(), entity_id=run.id, actor=ACTOR, action='rule_auto_approved',
                payload={'before': before, 'after': deepcopy(rule), 'job_id': job['id']}))
    job['auto_approved'] = job.get('auto_approved', 0) + len(approved)
