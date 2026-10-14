"""Owned, versioned verification contracts. Availability is never model-authored."""
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class Parameters(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class MeasurementParameters(Parameters):
    measurement: Literal['weight', 'height', 'width', 'length']
    comparison: Literal['lte', 'gte']
    threshold: float = Field(gt=0, strict=True)
    unit: Literal['oz', 'lb', 'g', 'kg', 'in', 'cm', 'mm']

    @model_validator(mode='after')
    def compatible_unit(self):
        if (self.measurement == 'weight') != (self.unit in {'oz', 'lb', 'g', 'kg'}):
            raise ValueError('Weight requires a mass unit; dimensions require a length unit.')
        return self


class FulfillmentParameters(Parameters):
    required_percent: float = Field(gt=0, le=100, strict=True)
    quantity_basis: Literal['picked', 'packed', 'shipped']
    order_basis: Literal['original_order', 'approved_current_order']


class SkuParameters(Parameters):
    maximum_unique_skus: int = Field(ge=1, strict=True)


class PoParameters(Parameters):
    maximum_unique_pos: int = Field(ge=1, strict=True)


class PlacementParameters(Parameters):
    required_checks: list[Literal['correct_face', 'clearance', 'no_seam_overlap', 'barcode_readable', 'no_obstruction']] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_checks(self):
        if len(set(self.required_checks)) != len(self.required_checks):
            raise ValueError('Choose each label inspection once.')
        self.required_checks.sort()
        return self


class AsnParameters(Parameters):
    reconcile_by: Literal['po_line', 'carton']


class DocumentParameters(Parameters):
    document_type: Literal['bill_of_lading', 'packing_list', 'asn']
    milestone: Literal['before_dispatch', 'before_arrival']


class CheckBinding(Parameters):
    version: Literal[1]

    @field_validator('version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Check version must be an integer.')
        return value


class MeasurementCheck(CheckBinding):
    check_id: Literal['package_measurement_limit']
    parameters: MeasurementParameters


class FulfillmentCheck(CheckBinding):
    check_id: Literal['po_line_fulfillment']
    parameters: FulfillmentParameters


class SkuCheck(CheckBinding):
    check_id: Literal['carton_sku_limit']
    parameters: SkuParameters


class PoCheck(CheckBinding):
    check_id: Literal['carton_po_limit']
    parameters: PoParameters


class PlacementCheck(CheckBinding):
    check_id: Literal['label_placement']
    parameters: PlacementParameters


class AsnCheck(CheckBinding):
    check_id: Literal['asn_reconciliation']
    parameters: AsnParameters


class DocumentCheck(CheckBinding):
    check_id: Literal['document_confirmation']
    parameters: DocumentParameters


StandardCheck = Annotated[Union[MeasurementCheck, FulfillmentCheck, SkuCheck, PoCheck, PlacementCheck, AsnCheck, DocumentCheck], Field(discriminator='check_id')]


class CheckDefinition(BaseModel):
    id: str
    version: int
    label: str
    verification: Literal['data', 'human', 'external_evidence']
    availability: Literal['implemented', 'not_implemented', 'manual', 'external']
    subjects: list[str]
    description: str
    required_data: list[str]
    parameters_schema: dict


# Version 1 semantics are immutable. A changed meaning requires a new version.
CATALOG = {
    'carton_po_limit': CheckDefinition(
        id='carton_po_limit', version=1, label='Carton PO limit',
        verification='data', availability='not_implemented', subjects=['carton'],
        description='Count distinct canonical PO identities in each complete carton and compare with the maximum. Never infer carton PO membership from the shipment or order header.',
        required_data=['Complete carton contents with authoritative PO identities on every allocation.'],
        parameters_schema=PoParameters.model_json_schema()),
    'package_measurement_limit': CheckDefinition(
        id='package_measurement_limit', version=1, label='Package measurement limit',
        verification='data', availability='implemented', subjects=['carton', 'pallet'],
        description='Compare each package measurement with an inclusive upper or lower bound. Convert compatible units; missing or incompatible measurements are unknown.',
        required_data=['Per-package weight, height, width or length as {value, unit}.'],
        parameters_schema=MeasurementParameters.model_json_schema()),
    'po_line_fulfillment': CheckDefinition(
        id='po_line_fulfillment', version=1, label='PO line fulfillment',
        verification='data', availability='not_implemented', subjects=['order'],
        description='Every PO line must reach at least the required percentage of its ordered quantity at the chosen quantity basis. Evaluate lines independently; excess on one line never offsets shortage on another. Original order includes every original line. Approved current order requires an authoritative revision including approved cancellations. Substitutions receive no credit without explicit line allocation.',
        required_data=['Complete ordered lines with stable PO and line IDs, ordered quantity and UOM.',
                       'Picked, packed or shipped quantities allocated to those exact PO line IDs.',
                       'Verified UOM conversions; never assume cases equal eaches.',
                       'Authoritative approved revision when approved_current_order is selected.'],
        parameters_schema=FulfillmentParameters.model_json_schema()),
    'carton_sku_limit': CheckDefinition(
        id='carton_sku_limit', version=1, label='Carton SKU limit',
        verification='data', availability='not_implemented', subjects=['carton'],
        description='Count distinct canonical product identities in each complete carton and compare with the maximum. Alias resolution and SKU normalization must be supplied by the inventory system.',
        required_data=['Complete carton contents and canonical product identities.'],
        parameters_schema=SkuParameters.model_json_schema()),
    'label_placement': CheckDefinition(
        id='label_placement', version=1, label='Label placement inspection',
        verification='human', availability='manual', subjects=['carton', 'pallet', 'label'],
        description='Inspect the selected placement criteria against the rule instruction and source diagram. Required face and clearances come from that evidence. No automatic pass is inferred from an illustration or package dimensions.',
        required_data=['Physical package and label, source diagram/instructions, and human inspection.'],
        parameters_schema=PlacementParameters.model_json_schema()),
    'asn_reconciliation': CheckDefinition(
        id='asn_reconciliation', version=1, label='ASN reconciliation',
        verification='data', availability='not_implemented', subjects=['shipment'],
        description='Reconcile the ASN against the final shipment at the selected granularity. Identities, quantities and UOM must match in both directions; missing or additional lines/containers are discrepancies.',
        required_data=['Complete final shipment contents and the corresponding ASN revision.',
                       'Stable PO line IDs or carton identifiers and verified UOM conversions.'],
        parameters_schema=AsnParameters.model_json_schema()),
    'document_confirmation': CheckDefinition(
        id='document_confirmation', version=1, label='Document confirmation',
        verification='external_evidence', availability='external', subjects=['shipment'],
        description='Obtain external confirmation that the required document exists for this shipment before the chosen milestone. Source-guide evidence alone is not shipment-specific confirmation.',
        required_data=['Shipment-linked document, confirmation timestamp and milestone timestamp.'],
        parameters_schema=DocumentParameters.model_json_schema()),
}


def check_definition(binding):
    # The typed binding validates the ID/version before it reaches the registry.
    return CATALOG[binding.check_id]


def needs_check_mapping(spec):
    from routing_guides.rule_catalog import instruction_only_check
    return not instruction_only_check(spec) and spec.schema_version == '1.2' and spec.purpose == 'shipment_validation' and spec.standard_check is None


def check_summary(spec):
    if spec.purpose == 'general_guidance':
        return 'General guidance'
    if spec.standard_check:
        check = check_definition(spec.standard_check)
        return f'{check.label} v{check.version} · {check.availability.replace("_", " ")}'
    from routing_guides.rule_catalog import instruction_only_check
    if instruction_only_check(spec):
        return 'Standard instruction · ' + spec.verification.replace('_', ' ')
    return 'Needs mapping' if needs_check_mapping(spec) else 'Legacy verification · not mapped to catalog'


class CheckStatus(BaseModel):
    label: str
    availability: Literal['implemented', 'not_implemented', 'manual', 'external', 'needs_mapping', 'legacy', 'guidance']


def check_status(spec) -> CheckStatus:
    if spec.purpose == 'general_guidance':
        return CheckStatus(label='General guidance', availability='guidance')
    if spec.standard_check:
        definition = check_definition(spec.standard_check)
        return CheckStatus(label=f'{definition.label} v{definition.version}', availability=definition.availability)
    from routing_guides.rule_catalog import instruction_only_check
    if instruction_only_check(spec):
        return CheckStatus(label='Standard instruction · manual verification', availability='manual' if spec.verification == 'human' else 'external')
    if needs_check_mapping(spec):
        return CheckStatus(label='Needs mapping to the shared catalog', availability='needs_mapping')
    return CheckStatus(label='Existing verification — not mapped to catalog', availability='legacy')
