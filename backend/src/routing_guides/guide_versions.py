"""Document lineage and conservative cross-guide conflict hints."""
from collections import defaultdict
import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from routing_guides.models import Guide


async def source_series(session, rules):
    ids = {UUID(str(rule['source_guide_id'])) for rule in rules}
    if not ids:
        return {}
    guides = (await session.scalars(select(Guide).where(Guide.id.in_(ids)))).all()
    if len(guides) != len(ids):
        raise HTTPException(409, 'A rule source document is unavailable.')
    return {str(guide.id): str(guide.series_id or guide.id) for guide in guides}


async def partition_baseline(session, guide, base):
    rules = base.payload['rules'] if base else []
    series = await source_series(session, rules)
    root = str(guide.series_id or guide.id)
    related = [rule for rule in rules if series[rule['source_guide_id']] == root]
    retained = [rule for rule in rules if series[rule['source_guide_id']] != root]
    return related, retained


async def protect_other_guides(session, guide, run, base, body):
    _, retained = await partition_baseline(session, guide, base)
    for rule in retained:
        if body.decisions.get(rule['stable_id'], 'retain') != 'retain':
            raise HTTPException(422, 'Rules from separate guides are retained. Open their source guide to change them.')
        body.decisions[rule['stable_id']] = 'retain'
    incoming = [rule for rule in run.payload['rules'] if rule['status'] == 'approved']
    series = await source_series(session, incoming)
    if any(series[rule['source_guide_id']] != str(guide.series_id or guide.id) for rule in incoming):
        raise HTTPException(422, 'This draft includes rules from a separate guide. Create a new draft for the selected guide.')


async def potential_conflicts(session, rules):
    series = await source_series(session, rules)
    grouped = defaultdict(list)
    for rule in rules:
        spec = rule['spec']
        if spec.get('purpose') == 'general_guidance':
            continue
        type_id = (spec.get('rule_type') or {}).get('id')
        key = (spec.get('subject'), type_id or spec['title'].strip().casefold())
        grouped[key].append(rule)
    conflicts = []
    for group in grouped.values():
        for i, left in enumerate(group):
            for right in group[i+1:]:
                if series[left['source_guide_id']] == series[right['source_guide_id']]:
                    continue
                fields = ('instruction', 'assertion', 'standard_check', 'applicability', 'applicability_text', 'exceptions', 'obligation')
                if all(left['spec'].get(field) == right['spec'].get(field) for field in fields):
                    continue
                conflicts.append({'left': left, 'right': right,
                    'reason': 'Different requirements for the same rule type or title across separate guides. Check scope and exceptions.'})
    return conflicts


def compare_editions(current, previous):
    """Content matching for navigation only; never carries an approval."""
    current = [r for r in current if r.get('status') not in {'ignored', 'rejected'}]
    def key(rule):
        return json.dumps({k: v for k, v in rule['spec'].items() if k != 'evidence'}, sort_keys=True)
    old_keys, new_keys = defaultdict(list), defaultdict(list)
    for rule in previous:
        old_keys[key(rule)].append(rule['stable_id'])
    for rule in current:
        new_keys[key(rule)].append(rule['id'])
    unchanged = {ids[0]: old_keys[value][0] for value, ids in new_keys.items()
                 if len(ids) == 1 and len(old_keys[value]) == 1}
    unmatched = [r for r in current if r['id'] not in unchanged]
    changed = {old['stable_id']: [r['id'] for r in unmatched
               if (r['spec']['title'].strip().casefold(), r['spec']['subject']) ==
                  (old['spec']['title'].strip().casefold(), old['spec']['subject'])]
               for old in previous if old['stable_id'] not in unchanged.values()}
    suggested = {rid for ids in changed.values() for rid in ids}
    return dict(unchanged=unchanged, changed={sid: ids for sid, ids in changed.items() if ids},
                added=[r['id'] for r in unmatched if r['id'] not in suggested],
                missing=[sid for sid, ids in changed.items() if not ids])
