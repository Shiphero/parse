"""Conservative review eligibility and exact matches; never infer semantic equivalence."""
import json
from collections import Counter, defaultdict

from routing_guides.rules import RuleSpec


def individual_review_reasons(spec, evidence_issues=(), duplicate=False):
    reasons = list(evidence_issues)
    if spec.purpose == 'unclassified':
        reasons.append('Choose general guidance or shipment validation before approval.')
    if spec.operational_category == 'unclassified' or not spec.consumption_points:
        reasons.append('Choose an operational category and consumption points before approval.')
    if duplicate:
        reasons.append('Possible duplicate or conflict: review matching titles together.')
    if spec.unresolved_questions or spec.verification == 'unresolved':
        reasons.append('Unresolved interpretation requires individual review.')
    if spec.exceptions:
        reasons.append('Review the exceptions individually.')
    if any(e.kind == 'visual' or e.region is not None for e in spec.evidence):
        reasons.append('Inspect visual source evidence individually.')
    return reasons


def duplicate_titles(rules):
    counts = Counter(r['spec']['title'].strip().casefold() for r in rules if r.get('status') != 'rejected')
    return {title for title, count in counts.items() if count > 1}

def exact_key(spec):
    spec = RuleSpec.model_validate(spec)
    # Page movement is harmless only for text citations that we validate again.
    # Visual descriptions alone cannot establish that an image stayed unchanged.
    if individual_review_reasons(spec):
        return None
    data = spec.model_dump(mode='json')
    for evidence in data['evidence']:
        evidence.pop('page')
    return json.dumps(data, sort_keys=True, separators=(',', ':'))


def compare_rules(rules, previous):
    duplicates = duplicate_titles(rules)
    old_keys, new_keys = defaultdict(list), defaultdict(list)
    for old in previous:
        key = exact_key(old['spec'])
        if key and old.get('review'):
            old_keys[key].append(old['stable_id'])
    for candidate in rules:
        key = exact_key(candidate['spec'])
        if key and not candidate.get('evidence_issues') and candidate['spec']['title'].strip().casefold() not in duplicates:
            new_keys[key].append(candidate['id'])
    unchanged = {ids[0]: old_keys[key][0] for key, ids in new_keys.items()
                 if len(ids) == 1 and len(old_keys[key]) == 1}
    matched_old = set(unchanged.values())
    unmatched = [r for r in rules if r['id'] not in unchanged]
    # Title matches are navigation hints only, never approval or retirement decisions.
    changed = {old['stable_id']: [r['id'] for r in unmatched
               if (r['spec']['title'].casefold().strip(), r['spec']['subject']) ==
                  (old['spec']['title'].casefold().strip(), old['spec']['subject'])]
               for old in previous if old['stable_id'] not in matched_old}
    suggested = {rid for ids in changed.values() for rid in ids}
    return dict(unchanged=unchanged,
                changed={sid: ids for sid, ids in changed.items() if ids},
                added=[r['id'] for r in unmatched if r['id'] not in suggested],
                missing=[sid for sid, ids in changed.items() if not ids])
