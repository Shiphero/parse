"""Source-backed changes, checked independently before touching a pending draft."""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field
from routing_guides.rules import EvidenceRef, RuleSpec, StrictModel

RESOLUTION_VERSION = 'rule-resolution-1.1'
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
    all_verified = bool(plan.changes) and all(verdicts.get(change.field) is True for change in plan.changes)
    apply = all_verified and automatic_change_allowed(old, new)
    record = ResolutionRecord(revision=candidate['revision'] + int(apply), input_fingerprint=fingerprint,
        provider=provider, model=model, at=datetime.now(timezone.utc).isoformat(),
        changes=[ResolutionChange(**change.model_dump(), before=old[change.field], after=new[change.field],
                                  verified=verdicts.get(change.field) is True, applied=apply) for change in plan.changes],
        questions=plan.questions, capability_gaps=plan.capability_gaps)
    return deepcopy(new if apply else old), record
