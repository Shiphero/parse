"""Stable requirement identity and presentation contracts, independent of verification."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from routing_guides.taxonomy import ConsumptionPoint, OperationalCategory
from routing_guides.check_catalog import check_definition


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class WorkflowArea(CatalogModel):
    workflow: ConsumptionPoint
    area: str
    label: str


class Placement(CatalogModel):
    workflow: ConsumptionPoint
    area: str
    enabled: bool = Field(default=True, strict=True)
    behavior: Literal['display', 'confirm', 'warn', 'block'] = 'display'


class RuleTypeBinding(CatalogModel):
    id: str
    version: Literal[1]

    @field_validator('version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Rule type version must be an integer.')
        return value


class RuleTypeDefinition(CatalogModel):
    id: str
    version: int = 1
    label: str
    description: str
    category: OperationalCategory
    required_purpose: Literal['general_guidance'] | None = None
    subjects: list[str]
    check_ids: list[str]
    allowed_placements: list[WorkflowArea]
    default_placements: list[Placement]


def area(workflow, identifier, label):
    return WorkflowArea(workflow=workflow, area=identifier, label=label)


def definition(identifier, label, description, category, subjects, checks, areas, required_purpose=None):
    return RuleTypeDefinition(id=identifier, label=label, description=description, category=category,
        subjects=subjects, check_ids=checks, allowed_placements=areas, required_purpose=required_purpose,
        # Extraction proposes display only; reviewers explicitly configure stronger behavior.
        default_placements=[Placement(workflow=areas[0].workflow, area=areas[0].area)])


PACK_CONTENTS = area('mobile_packing', 'carton_contents', 'Carton contents')
PACK_SELECTION = area('mobile_packing', 'carton_selection', 'Carton selection')
LABELS = [area('label_application', 'carton_labels', 'Carton labels'), area('mobile_packing', 'carton_labels', 'Carton labels')]
RULE_TYPES = {entry.id: entry for entry in [
    definition('general.guidance', 'General guidance', 'Broad expectations and reference policies, such as shipments arriving in excellent condition, on time and with proper documentation. Use specific types for measurable or actionable requirements.', 'business_administration', ['shipment', 'order', 'carton', 'pallet', 'item', 'label', 'document'], [], [area('supplier_management', 'general_guidance', 'General guidance')], required_purpose='general_guidance'),
    definition('carton.po_mixing', 'Carton PO mixing', 'Limits distinct purchase orders within each carton.', 'warehouse_operations', ['carton'], ['carton_po_limit'], [PACK_CONTENTS]),
    definition('carton.sku_mixing', 'Carton SKU mixing', 'Limits distinct products within each carton.', 'warehouse_operations', ['carton'], ['carton_sku_limit'], [PACK_CONTENTS]),
    definition('carton.measurement', 'Carton measurements', 'A weight or dimension limit for each carton.', 'warehouse_operations', ['carton'], ['package_measurement_limit'], [PACK_SELECTION]),
    definition('carton.protection', 'Protective packaging', 'Wrapping, cushioning or other protection inside a carton.', 'warehouse_operations', ['carton', 'item'], [], [area('mobile_packing', 'protective_packaging', 'Protective packaging')]),
    definition('carton.label_placement', 'Carton label placement', 'Physical label location, orientation and clearances; keep source diagrams and conditional variants.', 'warehouse_operations', ['carton', 'label'], ['label_placement'], LABELS),
    definition('carton.packing_documents', 'Packing documents on cartons', 'Physical insertion or attachment of packing documents.', 'warehouse_operations', ['carton', 'document'], [], [area('mobile_packing', 'packing_documents', 'Packing documents')]),
    definition('pallet.measurement', 'Pallet measurements', 'A weight or dimension limit for each pallet.', 'warehouse_operations', ['pallet'], ['package_measurement_limit'], [area('pallet_building', 'pallet_selection', 'Pallet selection')]),
    definition('pallet.stacking', 'Pallet stacking', 'Arrangement, stability and stacking of cartons on pallets.', 'warehouse_operations', ['pallet'], [], [area('pallet_building', 'stacking', 'Stacking')]),
    definition('pallet.wrapping', 'Pallet wrapping', 'Required physical wrapping or securing of a pallet.', 'warehouse_operations', ['pallet'], [], [area('pallet_building', 'wrapping', 'Wrapping')]),
    definition('pallet.label_placement', 'Pallet label placement', 'Physical location and visibility of pallet labels.', 'warehouse_operations', ['pallet', 'label'], ['label_placement'], [area('pallet_building', 'pallet_labels', 'Pallet labels'), area('label_application', 'pallet_labels', 'Pallet labels')]),
    definition('order.line_fulfillment', 'PO line fulfillment', 'Minimum fulfillment per PO line at an explicitly chosen stage.', 'business_administration', ['order'], ['po_line_fulfillment'], [area('order_management', 'fulfillment', 'Order fulfillment'), PACK_CONTENTS]),
    definition('transport.carrier_selection', 'Carrier selection', 'Permitted or required carriers and shipping services.', 'transportation_scheduling', ['shipment'], [], [area('transport_planning', 'carrier_selection', 'Carrier selection')]),
    definition('transport.pickup', 'Pickup arrangements', 'Booking and coordination of carrier pickup.', 'transportation_scheduling', ['shipment'], [], [area('pickup_scheduling', 'pickup', 'Pickup')]),
    definition('transport.approval', 'Shipment approval', 'Required authorization from a designated authority before loading, dispatch or arrival, including permission for floor-loaded or slip-sheet freight. Preserve destination, freight-mode conditions and exclusions.', 'transportation_scheduling', ['shipment'], ['approval_confirmation'], [area('transport_planning', 'shipment_approval', 'Shipment approval'), area('warehouse_loading', 'shipment_approval', 'Shipment approval')]),
    definition('transport.ship_deadline', 'Shipping deadlines', 'Shipment departure dates and windows.', 'transportation_scheduling', ['shipment', 'order'], [], [area('transport_planning', 'shipping_deadlines', 'Shipping deadlines')]),
    definition('transport.delivery', 'Delivery appointments', 'Delivery dates, windows and appointments.', 'transportation_scheduling', ['shipment'], [], [area('delivery_scheduling', 'delivery', 'Delivery appointments')]),
    definition('asn.reconciliation', 'ASN reconciliation', 'Consistency of ASN contents with the final shipment.', 'electronic_documents_edi', ['shipment'], ['asn_reconciliation'], [area('asn_generation', 'reconciliation', 'Reconciliation')]),
    definition('asn.contents', 'ASN contents', 'Required ASN identifiers, fields and hierarchy.', 'electronic_documents_edi', ['shipment', 'document'], [], [area('asn_generation', 'document_contents', 'Document contents')]),
    definition('edi.transmission', 'EDI transmission', 'Timing and destination of electronic document transmission.', 'electronic_documents_edi', ['shipment', 'document'], [], [area('edi_transmission', 'transmission_timing', 'Transmission timing')]),
    definition('document.confirmation', 'Document confirmation', 'Shipment-specific evidence of a required document before a milestone.', 'electronic_documents_edi', ['shipment'], ['document_confirmation'], [area('document_generation', 'document_confirmation', 'Document confirmation')]),
    definition('supplier.onboarding', 'Supplier onboarding', 'Supplier setup, enablement and certification activities.', 'business_administration', ['order', 'shipment', 'document'], [], [area('supplier_onboarding', 'onboarding', 'Onboarding')]),
    definition('supplier.contacts', 'Supplier contact maintenance', 'Maintenance of supplier contact information.', 'business_administration', ['order', 'shipment', 'document'], [], [area('supplier_management', 'contacts', 'Contacts')]),
    definition('product.setup', 'Product setup', 'Product master data and setup requirements.', 'business_administration', ['item', 'document'], [], [area('product_setup', 'product_setup', 'Product setup')]),
    definition('billing.requirements', 'Billing requirements', 'Invoice, payment and commercial billing instructions.', 'business_administration', ['order', 'document'], [], [area('billing', 'billing', 'Billing')]),
]}


def validate_delivery(spec):
    if spec.rule_type is None:
        if spec.placements:
            raise ValueError('Choose a standard rule type before assigning workflow areas.')
        return
    entry = RULE_TYPES.get(spec.rule_type.id)
    if entry is None or entry.version != spec.rule_type.version:
        raise ValueError('Unknown rule type or version. Choose an entry from the catalog.')
    if entry.required_purpose and spec.purpose != entry.required_purpose:
        raise ValueError('General guidance is for reference, not shipment validation.')
    if entry.required_purpose == 'general_guidance' and (spec.assertion is not None or spec.verification == 'data' or any(p.behavior != 'display' for p in spec.placements)):
        raise ValueError('General guidance is display only and cannot contain an automatic check.')
    if spec.subject not in entry.subjects:
        raise ValueError(f'{entry.label} requires subject: {", ".join(entry.subjects)}.')
    if spec.standard_check and spec.standard_check.check_id not in entry.check_ids:
        raise ValueError('The verification check does not match this rule type.')
    if spec.operational_category != entry.category:
        raise ValueError('Operational category must match the rule type catalog.')
    allowed = {(a.workflow, a.area) for a in entry.allowed_placements}
    used = [(p.workflow, p.area) for p in spec.placements]
    if not used or len(set(used)) != len(used) or any(pair not in allowed for pair in used):
        raise ValueError('Choose at least one unique, supported workflow area for this rule type.')
    if set(spec.consumption_points) != {p.workflow for p in spec.placements}:
        raise ValueError('Consumed by must match the assigned workflow placements, including disabled placements.')
    for placement in spec.placements:
        if placement.behavior in {'warn', 'block'}:
            if (spec.purpose != 'shipment_validation' or spec.standard_check is None
                    or check_definition(spec.standard_check).availability != 'implemented'):
                raise ValueError('Warning/blocking behavior requires an implemented automatic shipment check.')
        if placement.behavior == 'block' and spec.obligation not in {'required', 'prohibited'}:
            raise ValueError('Only required or prohibited obligations can block completion.')


def delivery_label(spec):
    return RULE_TYPES[spec.rule_type.id].label if spec.rule_type else 'Needs rule type mapping'


def instruction_only_check(spec):
    """Cataloged physical/admin instructions can be inspected without a numeric validator."""
    return (spec.rule_type is not None and not RULE_TYPES[spec.rule_type.id].check_ids
            and spec.verification in {'human', 'external_evidence'} and spec.assertion is None)
