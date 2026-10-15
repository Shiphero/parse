"""Apply classification metadata without inventing or replacing executable checks."""
from copy import deepcopy

from pydantic import ValidationError

from routing_guides.rule_catalog import RULE_TYPES
from routing_guides.rules import RuleSpec
from routing_guides.taxonomy import needs_classification


def needs_auto_classification(spec):
    return needs_classification(spec) or not spec.get('rule_type')


def apply_classification(original, classified):
    normalized = RuleSpec.model_validate(original).model_dump(mode='json')
    spec = deepcopy(normalized)
    if spec.get('purpose', 'unclassified') == 'unclassified':
        spec['purpose'] = classified.purpose
    if spec.get('operational_category', 'unclassified') == 'unclassified':
        spec['operational_category'] = classified.operational_category
    if not spec.get('consumption_points'):
        spec['consumption_points'] = classified.consumption_points
    reason = classified.reason
    if not spec.get('rule_type') and classified.rule_type:
        entry = RULE_TYPES[classified.rule_type.id]
        proposed = {**spec, 'rule_type': classified.rule_type.model_dump(mode='json'),
                    'operational_category': entry.category,
                    'placements': [p.model_dump(mode='json') for p in entry.default_placements],
                    'consumption_points': sorted({p.workflow for p in entry.default_placements})}
        try:
            # Keep original subjects, conditions and verification, even for legacy rules.
            RuleSpec.model_validate(proposed)
        except ValidationError:
            reason += ' Type not applied: it conflicts with the existing subject, purpose or verification; review the mapping.'
        else:
            spec = proposed
    if spec != normalized and spec.get('schema_version') != '1.2':
        spec['schema_version'] = '1.1'
    elif spec.get('schema_version') == '1.2' and spec['purpose'] == 'shipment_validation' and not spec.get('standard_check') and not spec.get('rule_type'):
        spec.update(verification='unresolved', assertion=None)
    return RuleSpec.model_validate(spec).model_dump(mode='json'), reason
