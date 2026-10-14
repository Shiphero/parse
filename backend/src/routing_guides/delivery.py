"""Resolve approved instructions into consumer areas without silently allowing unknowns."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from routing_guides.evaluator import expression, evaluate_rule
from routing_guides.rule_catalog import Placement, RULE_TYPES
from routing_guides.rules import RuleSpec
from routing_guides.taxonomy import ConsumptionPoint, needs_classification


class DeliveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    workflow: ConsumptionPoint
    area: str | None = None
    rule_type: str | None = None
    # Same canonical data shape as scenario evaluation. No ShipHero call or normalization here.
    snapshot: dict[str, Any] = Field(default_factory=dict)


class DeliveredSubject(BaseModel):
    subject_id: str
    applicability: Literal['applicable', 'not_applicable', 'unknown']
    action: Literal['display', 'confirm', 'warn', 'block', 'none', 'needs_information']
    check_outcome: Literal['pass', 'fail', 'cannot_determine', 'not_applicable'] | None = None
    reason: str


def scope(rule, facts):
    applicable, reason = expression(rule.applicability, facts) if rule.applicability else (True, 'Unconditional rule.')
    if applicable is False:
        return 'not_applicable', 'Applicability condition is false.'
    if applicable is None:
        return 'unknown', 'Applicability unknown: ' + reason
    exceptions = [expression(e.condition, facts)[0] if e.condition else None for e in rule.exceptions]
    if True in exceptions:
        return 'not_applicable', 'An approved exception applies.'
    if None in exceptions:
        return 'unknown', 'An exception needs more information.'
    if rule.unresolved_questions:
        return 'unknown', 'Unresolved: ' + '; '.join(rule.unresolved_questions)
    return 'applicable', reason


def subjects_for(rule, placement, snapshot):
    key = {'carton': 'cartons', 'pallet': 'pallets', 'item': 'items'}.get(rule.subject)
    targets = snapshot.get(key) if key else [snapshot.get('shipment', {})]
    if not isinstance(targets, list) or not targets or any(not isinstance(target, dict) for target in targets):
        return [DeliveredSubject(subject_id='unknown', applicability='unknown', action='needs_information', reason='No complete subject data supplied.')]
    result = []
    for i, target in enumerate(targets):
        shipment = snapshot.get('shipment', {})
        evidence = snapshot.get('evidence', {})
        facts = {**target, 'shipment': shipment, 'evidence': evidence}
        applicable, reason = scope(rule, facts)
        action = 'none' if applicable == 'not_applicable' else 'needs_information' if applicable == 'unknown' else placement.behavior
        outcome = None
        if applicable == 'applicable' and placement.behavior in {'warn', 'block'}:
            one = {**snapshot, key: [target]} if key else snapshot
            evaluation = evaluate_rule('delivery', rule, one)
            outcome = evaluation['outcome']
            reason = evaluation['subjects'][0]['reason'] if evaluation['subjects'] else evaluation['reason']
            action = ('none' if outcome in {'pass', 'not_applicable'} else
                      placement.behavior if outcome == 'fail' else 'needs_information')
        result.append(DeliveredSubject(subject_id=str(target.get('id', i+1)), applicability=applicable,
                                      action=action, check_outcome=outcome, reason=reason))
    return result


def selected_placements(spec, request):
    if spec.rule_type is None or needs_classification(spec.model_dump()):
        return []
    if request.rule_type and request.rule_type != spec.rule_type.id:
        return []
    return [p for p in spec.placements if p.workflow == request.workflow and (request.area is None or p.area == request.area)]


def validate_selection(request):
    if request.rule_type is not None and request.rule_type not in RULE_TYPES:
        raise ValueError('Unknown standard rule type.')
    entries = [RULE_TYPES[request.rule_type]] if request.rule_type else RULE_TYPES.values()
    areas = [a for entry in entries for a in entry.allowed_placements if a.workflow == request.workflow]
    if request.rule_type and not areas:
        raise ValueError('The rule type does not support this workflow.')
    if request.area is not None and not any(a.area == request.area for a in areas):
        raise ValueError('Unknown workflow area for the selected rule type and workflow.')
