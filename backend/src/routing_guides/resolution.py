"""Source-backed changes, checked independently before touching a pending draft."""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field, ValidationError
from routing_guides.rules import EvidenceRef, RuleSpec, StrictModel

RESOLUTION_VERSION = 'rule-resolution-1.4'
ChangeField = Literal['title', 'instruction', 'purpose', 'operational_category', 'consumption_points',
    'rule_type', 'placements', 'verification', 'standard_check', 'applicability_text', 'applicability',
    'exceptions', 'unresolved_questions', 'execution_mode', 'evidence', 'subject', 'obligation', 'assertion', 'schema_version']


class SupportedChange(StrictModel):
    field: ChangeField
    explanation: str = Field(min_length=1, max_length=1500)
    sources: list[EvidenceRef] = Field(min_length=1, max_length=12)


class RemainingQuestion(StrictModel):
    section: Literal['instruction', 'classification', 'conditions', 'verification', 'evidence', 'advanced']
    question: str = Field(min_length=1, max_length=1500)
    sources: list[EvidenceRef] = Field(default_factory=list, max_length=12)


class ResolutionPlan(StrictModel):
    proposed_spec: RuleSpec | None
    changes: list[SupportedChange] = Field(default_factory=list, max_length=24)
    questions: list[RemainingQuestion] = Field(default_factory=list, max_length=20)
    capability_gaps: list[str] = Field(default_factory=list, max_length=10)


class ResolutionChange(SupportedChange):
    before: Any
    after: Any
    verified: bool = False
    applied: bool = False


class ResolutionRecord(StrictModel):
    revision: int
    input_fingerprint: str
    prompt_version: str = RESOLUTION_VERSION
    provider: str
    model: str
    at: str
    changes: list[ResolutionChange] = Field(default_factory=list)
    questions: list[RemainingQuestion] = Field(default_factory=list)
    capability_gaps: list[str] = Field(default_factory=list)
    failed: bool = False
    job_id: str | None = None
    verifier_model: str | None = None
    output_fingerprint: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    validation_fields: list[str] = Field(default_factory=list)


def preparation_targets(candidate: dict) -> list[str]:
    """Repair concrete gaps; final assessment still checks every complete rule."""
    from routing_guides.check_catalog import needs_check_mapping
    from routing_guides.taxonomy import needs_classification
    spec = RuleSpec.model_validate(candidate['spec'])
    targets = []
    if needs_classification(candidate['spec']):
        targets.append('Fill missing purpose, operational category or consuming workflows; preserve known classifications.')
    if (spec.rule_type is None and spec.execution_mode != 'reference_only') or needs_check_mapping(spec):
        targets.append('Resolve the missing rule type or check mapping, without inventing a validator or retailer policy.')
    if spec.unresolved_questions:
        targets.append('Resolve only the recorded questions that the supplied source answers; retain genuine uncertainty.')
    if candidate.get('evidence_issues'):
        targets.append('Resolve the recorded source discrepancies while preserving original evidence: ' + '; '.join(candidate['evidence_issues']))
    assessment = candidate.get('assessment') or {}
    # A stale recommendation cannot justify changing a newer definition.
    if assessment.get('revision') == candidate['revision'] and not assessment.get('check_failed'):
        targets.extend(issue['action'] for issue in assessment.get('issues', []) if issue.get('kind') == 'correction')
    return targets


def correction_groups(plan: ResolutionPlan) -> list[set[str]]:
    """Policy, bindings and routing are coupled; question cleanup is separate."""
    fields = {change.field for change in plan.changes}
    return [group for group in (fields - {'unresolved_questions'}, fields & {'unresolved_questions'}) if group]


def group_spec(original: dict, plan: ResolutionPlan, fields: set[str]) -> dict:
    proposed = plan.proposed_spec.model_dump(mode='json')
    return RuleSpec.model_validate({**original, **{key: proposed[key] for key in fields}}).model_dump(mode='json')


def validate_plan(original: dict, plan: ResolutionPlan, pages: dict[int, str | None]) -> None:
    from routing_guides.analysis_jobs import normalized_excerpt
    old = RuleSpec.model_validate(original).model_dump(mode='json')
    new = plan.proposed_spec.model_dump(mode='json') if plan.proposed_spec else old
    changed = {key for key in old if old[key] != new[key]}
    named = [change.field for change in plan.changes]
    if len(set(named)) != len(named) or set(named) != changed:
        raise ValueError('Every changed field must have exactly one explanation and source.')
    for item in [*plan.changes, *plan.questions]:
        for source in item.sources:
            quote = normalized_excerpt(source.quote)
            if source.kind != 'text' or source.region is not None or not quote or quote not in normalized_excerpt(pages.get(source.page)):
                raise ValueError('A proposed change has an unsupported source citation.')
    if plan.proposed_spec:
        # Adding citations is allowed; original evidence is immutable in automatic work.
        for evidence in old['evidence']:
            if evidence not in new['evidence']:
                raise ValueError('Automatic resolution cannot remove original evidence.')
        for evidence in new['evidence']:
            if evidence not in old['evidence']:
                quote = normalized_excerpt(evidence['quote'])
                if evidence['kind'] != 'text' or evidence.get('region') or not quote or quote not in normalized_excerpt(pages.get(evidence['page'])):
                    raise ValueError('New evidence must match source text.')


def automatic_change_allowed(original: dict, proposed: dict) -> bool:
    # Preserve obligation, subject, custom expressions and existing shipment controls.
    for key in ('obligation', 'subject', 'schema_version', 'assertion'):
        if original[key] != proposed[key]:
            return False
    # Verified catalog corrections and display routing can replace existing mappings.
    # Shipment enforcement still requires an explicit decision.
    if any(p.get('behavior') != 'display' or not p.get('enabled', True) for p in original['placements']):
        return False
    if any(p.get('behavior') != 'display' or not p.get('enabled', True) for p in proposed['placements']):
        return False
    return True


def resolve_plan(candidate: dict, plan: ResolutionPlan, verdicts: dict[str, bool], pages: dict,
                 provider: str, model: str, fingerprint: str) -> tuple[dict, ResolutionRecord]:
    validate_plan(candidate['spec'], plan, pages)
    old = RuleSpec.model_validate(candidate['spec']).model_dump(mode='json')
    new = plan.proposed_spec.model_dump(mode='json') if plan.proposed_spec else old
    applied = set()
    result = old
    for group in correction_groups(plan):
        if not all(verdicts.get(field) is True for field in group):
            continue
        try:
            selected = group_spec(result, plan, group)
        except ValidationError:
            continue
        if automatic_change_allowed(old, selected):
            result = selected
            applied.update(group)
    record = ResolutionRecord(revision=candidate['revision'] + int(bool(applied)), input_fingerprint=fingerprint,
        provider=provider, model=model, at=datetime.now(timezone.utc).isoformat(),
        changes=[ResolutionChange(**change.model_dump(), before=old[change.field], after=new[change.field],
                                  verified=verdicts.get(change.field) is True, applied=change.field in applied) for change in plan.changes],
        questions=plan.questions, capability_gaps=plan.capability_gaps)
    return deepcopy(result), record
