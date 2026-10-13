"""Versioned rule contracts and a deliberately bounded, non-executable rule language."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from routing_guides.check_catalog import StandardCheck, check_definition
from routing_guides.taxonomy import OperationalCategory, ConsumptionPoint, canonical_consumption_points


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


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
            if self.op in {'count', 'unique_count'} and self.unit is not None:
                raise ValueError('Counts have no measurement unit.')
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
    schema_version: Literal['1.0', '1.1', '1.2'] = '1.1'
    operational_category: OperationalCategory = Field(default='unclassified', description='Primary operational activity; independent of purpose and verification.')
    consumption_points: list[ConsumptionPoint] = Field(default_factory=list, description='Workflows enforcing or presenting this obligation, not upstream data sources.')
    purpose: Literal['general_guidance', 'shipment_validation', 'unclassified'] = Field(default='unclassified', description='Intended use, independent of verification method. General guidance is excluded from shipment checks; unclassified requires review.')
    title: str = Field(min_length=1, max_length=250)
    instruction: str = Field(min_length=1)
    subject: Literal['shipment', 'order', 'pallet', 'carton', 'item', 'label', 'document']
    obligation: Literal['required', 'prohibited', 'recommended', 'informational']
    verification: Literal['data', 'human', 'external_evidence', 'unresolved']
    applicability_text: str = Field(min_length=1)
    applicability: Expression | None = None
    exceptions: list[ExceptionRule] = Field(default_factory=list)
    assertion: Expression | None = Field(default=None, description='True means compliance, even for prohibited obligations')
    standard_check: StandardCheck | None = Field(default=None, description='Versioned shared check binding. Never invent IDs or availability; null means needs mapping for schema 1.2 shipment rules.')
    evidence: list[EvidenceRef] = Field(min_length=1)
    unresolved_questions: list[str] = Field(default_factory=list)

    @field_validator('consumption_points')
    @classmethod
    def unique_consumers(cls, value):
        return canonical_consumption_points(value)

    @model_validator(mode='after')
    def executable(self):
        if self.standard_check is not None:
            definition = check_definition(self.standard_check)
            if self.schema_version != '1.2':
                raise ValueError('Catalog checks require rule schema 1.2.')
            if self.subject not in definition.subjects or self.verification != definition.verification:
                raise ValueError('Subject and verification must match the selected catalog check.')
            if self.assertion is not None:
                raise ValueError('Catalog checks cannot also contain a custom assertion.')
        elif self.schema_version == '1.2' and self.purpose == 'shipment_validation':
            if self.verification != 'unresolved' or self.assertion is not None:
                raise ValueError('Unmapped catalog rules must use unresolved verification with no assertion.')
        if self.verification == 'data' and self.assertion is None and self.standard_check is None:
            raise ValueError('Data verification requires a compliance assertion.')
        return self


class PageCoverage(StrictModel):
    page: int = Field(ge=1)
    outcome: Literal['rules_found', 'no_rules', 'needs_review']
    note: str


class Extraction(StrictModel):
    rules: list[RuleSpec]
    coverage: list[PageCoverage]
    warnings: list[str] = Field(default_factory=list)


class EvaluationItem(StrictModel):
    rule_id: str
    title: str
    instruction: str
    obligation: str
    outcome: Literal['pass', 'fail', 'cannot_determine', 'not_applicable']
    reason: str
    subjects: list[dict[str, Any]] = Field(default_factory=list)
