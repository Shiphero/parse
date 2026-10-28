"""Readiness contracts and pure checks used by manual and automatic draft review."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Literal
from uuid import uuid4

from pydantic import Field
from routing_guides.rules import RuleSpec, StrictModel
from routing_guides.check_catalog import needs_check_mapping
from routing_guides.taxonomy import needs_classification

PROMPT_VERSION = 'rule-review-assessment-3.0'
MAX_DUPLICATE_COMPARISONS = 8
CONFIDENCE_THRESHOLD = 0.95
Section = Literal['instruction', 'classification', 'conditions', 'verification', 'evidence', 'advanced']


class AssessmentIssue(StrictModel):
    code: str
    section: Section
    action: str
    kind: Literal['correction', 'manual']
    related_rule_ids: list[str] = Field(default_factory=list)


class AssessmentDimension(StrictModel):
    name: str
    choice: Literal['supported', 'correction', 'uncertain']
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    probabilities: dict[str, float]


class DuplicateAssessment(StrictModel):
    rule_id: str
    title: str
    source_pages: list[int]
    choice: Literal['duplicate', 'distinct', 'conflict', 'uncertain']
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    probabilities: dict[str, float]


class AssessmentResult(StrictModel):
    outcome: Literal['ready', 'needs_correction', 'needs_review']
    issues: list[AssessmentIssue]
    check_failed: bool = False
    auto_approval_supported: bool = False
    resolution_fingerprint: str | None = None
    execution_gaps: list[str] = Field(default_factory=list)
    dimensions: list[AssessmentDimension]
    duplicates: list[DuplicateAssessment] = Field(default_factory=list)
    duplicate_candidates: int = 0
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    threshold: float = CONFIDENCE_THRESHOLD
    fingerprint: str
    revision: int
    job_id: str
    assessed_at: str
    provider: Literal['jev'] = 'jev'
    model: str
    prompt_version: str = PROMPT_VERSION
    source_pages: list[int]
    usage: dict = Field(default_factory=dict)


def new_assessment_job(selected: list[dict], model: str, actor: str, scope: str) -> dict:
    from routing_guides.review_processing import now
    return {'id': str(uuid4()), 'prompt_version': PROMPT_VERSION, 'provider': 'jev', 'model': model,
            'actor': actor, 'status': 'queued' if selected else 'complete', 'scope': scope,
            'pending': [{'id': r['id'], 'revision': r['revision']} for r in selected],
            'total': len(selected), 'processed': 0, 'assessed': 0, 'failed': 0, 'skipped': 0, 'error': None,
            'started_at': now(), 'updated_at': now(), 'reused_assessments': 0}


# Retrieval proposes comparisons; only Jev judges semantic equivalence.
_STOP_WORDS = set('a an and are as at be by for from in is it must of on or shall should that the their this to with all each any'.split())


def rule_terms(rule: dict) -> set[str]:
    spec = rule['spec']
    text = spec['title'] + ' ' + spec['instruction']
    words = re.findall(r"[a-z]+", text.casefold())
    return {word[:-1] if len(word) > 4 and word.endswith('s') else word
            for word in words if word not in _STOP_WORDS and len(word) > 1}


@dataclass
class DuplicateIndex:
    rules: list[dict]
    terms: dict[str, set[str]]
    weights: dict[str, float]


def duplicate_index(rules: list[dict]) -> DuplicateIndex:
    active = [r for r in rules if r['status'] not in {'rejected', 'ignored'}]
    terms = {r['id']: rule_terms(r) for r in active}
    counts = Counter(term for values in terms.values() for term in values)
    weights = {term: math.log((len(active) + 1) / (count + 1)) + 1 for term, count in counts.items()}
    return DuplicateIndex(active, terms, weights)


def related_rules(candidate: dict, index: DuplicateIndex) -> list[dict]:
    terms = index.terms.get(candidate['id'], rule_terms(candidate))
    title = candidate['spec']['title'].strip().casefold()
    ranked = []
    for other in index.rules:
        if other['id'] == candidate['id']:
            continue
        other_terms = index.terms[other['id']]
        overlap = terms & other_terms
        union = terms | other_terms
        score = sum(index.weights.get(t, 1) for t in overlap) / (sum(index.weights.get(t, 1) for t in union) or 1)
        exact_title = other['spec']['title'].strip().casefold() == title
        if exact_title or len(overlap) >= 2 and score >= 0.18:
            ranked.append((2 if exact_title else score, other))
    return [rule for _, rule in sorted(ranked, key=lambda pair: (-pair[0], pair[1]['id']))]


def assessment_fingerprint(candidate: dict, related: list[dict]) -> str:
    # Results cannot survive edits, decisions, or changes to known matching rules.
    fields = ('id', 'revision', 'status', 'spec', 'source_guide_id', 'review', 'evidence_issues')
    value = [{**{key: r.get(key) for key in fields},
              'spec': RuleSpec.model_validate(r['spec']).model_dump(mode='json'),
              'evidence_issues': r.get('evidence_issues') or []}
             for r in [candidate, *related]]
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def local_issues(candidate: dict, related: list[dict], pages: dict[int, str | None]) -> list[AssessmentIssue]:
    from routing_guides.analysis_jobs import evidence_issues
    spec = RuleSpec.model_validate(candidate['spec'])
    result = []
    def add(code, section, action, kind='manual', related_ids=None):
        result.append(AssessmentIssue(code=code, section=section, action=action, kind=kind,
                                      related_rule_ids=related_ids or []))
    for issue in dict.fromkeys([*candidate.get('evidence_issues', []), *evidence_issues(spec, pages)]):
        add('source_mismatch', 'evidence', issue, 'correction')
    if needs_classification(candidate['spec']):
        add('classification_missing', 'classification', 'Choose the rule purpose, operational category and consuming workflows.')
    if spec.rule_type is None and spec.execution_mode != 'reference_only':
        add('type_missing', 'classification', 'A compatible rule type has not been established. Resolve the mapping or record the requirement for reference.')
    if needs_check_mapping(spec):
        add('check_missing', 'verification', 'Automatic verification has not been configured. Resolve the mapping or record the requirement for reference.')
    for question in spec.unresolved_questions:
        add('unresolved_question', 'advanced', f'Resolve this question against the source: {question}')
    for reference in spec.evidence:
        if reference.kind == 'visual' or reference.region is not None:
            add('visual_evidence', 'evidence', f'Inspect the original image on PDF page {reference.page}; this text assessment cannot verify the visual evidence.')
        if not pages.get(reference.page):
            add('missing_source', 'evidence', f'Read PDF page {reference.page}; usable source text is unavailable.')
    if any(not p.enabled for p in spec.placements):
        add('disabled_workflow', 'classification', 'Confirm that the disabled workflow placements are intentional, or enable the required placements.')
    if any(p.behavior in {'warn', 'block'} for p in spec.placements):
        add('enforcement', 'classification', 'Review the conditions and check before allowing this rule to warn or block shipment processing.')
    return result


def choose_sample(rules: list[dict], limit: int) -> list[dict]:
    """Round-robin across categories, verification modes and review flags."""
    buckets = defaultdict(list)
    for rule in rules:
        if rule['status'] == 'pending':
            spec = rule['spec']
            key = (spec.get('operational_category'), spec['verification'], bool(spec.get('unresolved_questions') or rule.get('evidence_issues')))
            buckets[key].append(rule)
    chosen = []
    while len(chosen) < limit and any(buckets.values()):
        for bucket in buckets.values():
            if bucket and len(chosen) < limit:
                chosen.append(bucket.pop(0))
    return chosen
