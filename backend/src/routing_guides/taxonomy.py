"""Operational ownership and consumers, independent of rule use and verification."""
from typing import Literal

OperationalCategory = Literal['warehouse_operations', 'transportation_scheduling', 'electronic_documents_edi', 'business_administration', 'unclassified']
ConsumptionPoint = Literal[
    'mobile_picking', 'mobile_packing', 'label_generation', 'label_application',
    'pallet_building', 'warehouse_loading', 'transport_planning', 'pickup_scheduling',
    'delivery_scheduling', 'document_generation', 'document_transmission', 'asn_generation', 'edi_transmission',
    'supplier_onboarding', 'supplier_management', 'product_setup', 'order_management',
    'billing', 'compliance_disputes',
]


def canonical_consumption_points(value: list[ConsumptionPoint]) -> list[ConsumptionPoint]:
    if len(value) != len(set(value)):
        raise ValueError('Consumption points must be unique.')
    return sorted(value)


def needs_classification(spec: dict) -> bool:
    return (spec.get('purpose', 'unclassified') == 'unclassified'
            or spec.get('operational_category', 'unclassified') == 'unclassified'
            or not spec.get('consumption_points'))


TAXONOMY_GUIDANCE = '''Assign operational_category and consumption_points independently of purpose, subject, obligation and verification. Category identifies the required activity; consumption points identify the exact workflows that MUST enforce or present this rule, not every system supplying its data.
warehouse_operations: physical picking, packing, wrapping, carton assortment, pallet construction, label application, staging and loading. Consumers: mobile_picking, mobile_packing, label_application, pallet_building, warehouse_loading; label_generation for physical label production requirements.
transportation_scheduling: carrier/service selection, routing, pickup, ship-by dates, delivery windows and appointments. Consumers: transport_planning, pickup_scheduling, delivery_scheduling. A shipment deadline is not mobile_packing merely because pack data feeds shipping.
electronic_documents_edi: electronic document content, identifiers and mappings, ASN carton/pallet hierarchy and accuracy, EDI transaction content and transmission timing. Consumers: document_generation, document_transmission, label_generation, asn_generation, edi_transmission. Use document_transmission for emailing/uploading packing lists and BOLs; edi_transmission is for structured EDI messages such as 856 ASNs and 855 acknowledgements. ASN requirements belong here, NOT business_administration or warehouse_operations just because they use packing data.
business_administration: supplier onboarding and contacts, EDI connectivity/certification onboarding, product/master-data setup, order administration, billing procedures and disputes. Consumers: supplier_onboarding, supplier_management, product_setup, order_management, billing, compliance_disputes.
Examples: one PO per carton -> warehouse_operations / mobile_packing; wrap pallets -> warehouse_operations / pallet_building; apply carton label at a specified location -> warehouse_operations / label_application; put packing list on lead carton -> warehouse_operations / mobile_packing; required packing-list fields -> electronic_documents_edi / document_generation; ASN contents match packed cartons -> electronic_documents_edi / asn_generation; transmit ASN before arrival -> electronic_documents_edi / edi_transmission; arrange carrier pickup -> transportation_scheduling / pickup_scheduling; ship within PO dates -> transportation_scheduling / transport_planning; maintain Ulta contacts -> business_administration / supplier_management; respond to OpenText onboarding invitation -> business_administration / supplier_onboarding.
Choose one primary category and the smallest justified nonempty set of consumption points. Multiple consumers are allowed only when the SAME obligation is enforced in each. Never route an ASN rule to mobile_packing only because packing captures carton contents or SSCCs. Categorize by the required action, not keywords, document sections or which department happens to do the work. During extraction, split independent obligations (e.g. wrap pallet, arrange pickup, transmit ASN) into separate rules retaining source citations. During classification of existing rules, do not split or rewrite: genuinely inseparable/mixed instructions may use unclassified with an empty consumption_points list and an explanatory reason. Preserve known classifications supplied in current_classification; fill only missing dimensions.'''
