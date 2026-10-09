"""Versioned rule contracts and a deliberately bounded, non-executable rule language."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Expression(StrictModel):
    op: Literal['eq', 'ne', 'lt', 'lte', 'gt', 'gte', 'in', 'exists', 'all', 'any', 'not', 'count', 'sum', 'unique_count']
    path: str | None = None
    value: str | int | float | bool | list[str | int | float] | None = None
    unit: Literal['oz', 'lb', 'g', 'kg', 'in', 'cm', 'mm'] | None = None
    comparator: Literal['eq', 'ne', 'lt', 'lte', 'gt', 'gte'] | None = None
    children: list['Expression'] = Field(default_factory=list)

    @model_validator(mode='after')
    def valid_shape(self):
        if self.op in {'all', 'any', 'not'}:
            if not self.children or (self.op == 'not' and len(self.children) != 1):
                raise ValueError('Boolean expressions require children; not requires exactly one.')
            if any(x is not None for x in (self.path, self.value, self.unit, self.comparator)):
                raise ValueError('Boolean expressions accept only children.')
        else:
            if not self.path or self.children:
                raise ValueError('Field expressions require a path and no children.')
            if any(not (part == '*' or part.replace('_', '').isalnum()) for part in self.path.split('.')):
                raise ValueError('Paths use field names separated by dots; * expands an array.')
            aggregate = self.op in {'count', 'sum', 'unique_count'}
            if aggregate != (self.comparator is not None):
                raise ValueError('Aggregates require a comparator; other expressions do not.')
            if self.op == 'in' and not isinstance(self.value, list):
                raise ValueError('in requires a list of allowed values.')
            if self.op != 'exists' and self.value is None:
                raise ValueError('A comparison value is required.')
            if self.op == 'exists' and (self.value is not None or self.unit is not None):
                raise ValueError('exists takes no comparison value or unit.')
        def size(node, depth=0):
            if depth > 16:
                raise ValueError('Expression nesting exceeds 16 levels.')
            return 1 + sum(size(c, depth+1) for c in node.children)
        if size(self) > 256:
            raise ValueError('Expression exceeds 256 nodes.')
        return self


class EvidenceRef(StrictModel):
    page: int = Field(ge=1, description='One-based PDF page, not the printed page number')
    quote: str = Field(min_length=1)
    kind: Literal['text', 'visual'] = 'text'
    region: list[float] | None = Field(default=None, description='Optional normalized x,y,width,height for visual evidence')

    @model_validator(mode='after')
    def region_bounds(self):
        if self.region is not None:
            if len(self.region) != 4 or any(not 0 <= n <= 1 for n in self.region):
                raise ValueError('Region requires four normalized coordinates.')
            x, y, w, h = self.region
            if not w or not h or x+w > 1 or y+h > 1:
                raise ValueError('Region must fit the page.')
        return self


class ExceptionRule(StrictModel):
    description: str
    condition: Expression | None = None


class RuleSpec(StrictModel):
    schema_version: Literal['1.0'] = '1.0'
    title: str = Field(min_length=1, max_length=250)
    instruction: str = Field(min_length=1)
    subject: Literal['shipment', 'order', 'pallet', 'carton', 'item', 'label', 'document']
    obligation: Literal['required', 'prohibited', 'recommended', 'informational']
    verification: Literal['data', 'human', 'external_evidence', 'unresolved']
    applicability_text: str = Field(min_length=1)
    applicability: Expression | None = None
    exceptions: list[ExceptionRule] = Field(default_factory=list)
    assertion: Expression | None = Field(default=None, description='True means compliance, even for prohibited obligations')
    evidence: list[EvidenceRef] = Field(min_length=1)
    unresolved_questions: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def executable(self):
        if self.verification == 'data' and self.assertion is None:
            raise ValueError('Data verification requires a compliance assertion.')
        return self


class PageCoverage(StrictModel):
    page: int = Field(ge=1)
    outcome: Literal['rules_found', 'no_rules', 'needs_review']
    note: str


class Extraction(StrictModel):
    rules: list[RuleSpec]
    coverage: list[PageCoverage]
    warnings: list[str]


class EvaluationItem(StrictModel):
    rule_id: str
    title: str
    instruction: str
    obligation: str
    outcome: Literal['pass', 'fail', 'cannot_determine', 'not_applicable']
    reason: str
    subjects: list[dict[str, Any]] = Field(default_factory=list)
