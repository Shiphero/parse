import unittest
from uuid import uuid4

from pydantic import ValidationError

from routing_guides.classification_mapping import apply_classification, needs_auto_classification
from routing_guides.classification_provider import Classification
from test_rules import rule


def classification(type_id=None):
    return Classification(id=uuid4(), purpose='shipment_validation',
        operational_category='warehouse_operations', consumption_points=['mobile_packing'],
        rule_type={'id': type_id, 'version': 1} if type_id else None, reason='Classified from the source instruction.')


class ClassificationMappingTests(unittest.TestCase):
    def test_existing_classification_without_type_is_eligible(self):
        self.assertTrue(needs_auto_classification(rule().model_dump(mode='json')))

    def test_type_mapping_preserves_evidence_and_executable_assertion(self):
        before = rule().model_dump(mode='json')
        after, _ = apply_classification(before, classification('carton.measurement'))
        self.assertEqual(after['rule_type']['id'], 'carton.measurement')
        self.assertEqual(after['placements'], [{'workflow': 'mobile_packing', 'area': 'carton_selection', 'enabled': True, 'behavior': 'display'}])
        for key in ['instruction', 'evidence', 'assertion', 'verification', 'applicability', 'exceptions']:
            self.assertEqual(after[key], before[key])
        self.assertIsNone(before['rule_type'])

    def test_unmatched_legacy_automatic_rule_is_not_changed(self):
        before = rule(schema_version='1.0').model_dump(mode='json')
        after, _ = apply_classification(before, classification())
        self.assertEqual(after, before)

    def test_incompatible_type_stays_unmapped_with_reason(self):
        before = rule().model_dump(mode='json')
        after, reason = apply_classification(before, classification('pallet.measurement'))
        self.assertEqual(after, before)
        self.assertIn('Type not applied', reason)

    def test_existing_type_and_disabled_placement_are_preserved(self):
        before = rule(rule_type={'id': 'carton.measurement', 'version': 1},
            placements=[{'workflow': 'mobile_packing', 'area': 'carton_selection', 'enabled': False}]).model_dump(mode='json')
        after, _ = apply_classification(before, classification('carton.protection'))
        self.assertEqual(after, before)

    def test_uninvented_catalog_ids_only(self):
        with self.assertRaises(ValidationError):
            classification('invented.type')
