import unittest
from pydantic import ValidationError
from routing_guides.rules import RuleSpec
from routing_guides.review import compare_rules, individual_review_reasons
from routing_guides.taxonomy import needs_classification
from test_rules import rule


class TaxonomyTests(unittest.TestCase):
    def test_legacy_is_readable_but_not_assigned_to_a_consumer(self):
        data = rule().model_dump(mode='json')
        data.update(schema_version='1.0')
        data.pop('operational_category')
        data.pop('consumption_points')
        legacy = RuleSpec.model_validate(data)
        self.assertEqual(legacy.operational_category, 'unclassified')
        self.assertEqual(legacy.consumption_points, [])
        self.assertTrue(needs_classification(data))
        self.assertTrue(individual_review_reasons(legacy))

    def test_consumers_are_bounded_unique_and_order_independent(self):
        for changes in ({'operational_category': 'other'}, {'consumption_points': ['unknown']}, {'consumption_points': ['mobile_packing', 'mobile_packing']}):
            with self.assertRaises(ValidationError):
                rule(**changes)
        left = rule(consumption_points=['mobile_packing', 'label_application']).model_dump(mode='json')
        right = rule(consumption_points=['label_application', 'mobile_packing']).model_dump(mode='json')
        old = [{'stable_id': 'old', 'spec': left, 'review': {'actor': 'Reviewer'}}]
        self.assertEqual(compare_rules([{'id': 'new', 'spec': right}], old)['unchanged'], {'new': 'old'})
        right['consumption_points'] = ['asn_generation']
        self.assertEqual(compare_rules([{'id': 'new', 'spec': right}], old)['unchanged'], {})
        right = {**left, 'operational_category': 'electronic_documents_edi'}
        self.assertEqual(compare_rules([{'id': 'new', 'spec': right}], old)['unchanged'], {})

    def test_use_and_verification_are_independent_of_operational_area(self):
        spec = rule(operational_category='electronic_documents_edi', consumption_points=['asn_generation'], verification='external_evidence')
        self.assertEqual(spec.purpose, 'shipment_validation')
        self.assertFalse(needs_classification(spec.model_dump()))
        guidance = rule(purpose='general_guidance', operational_category='business_administration', consumption_points=['supplier_onboarding'])
        self.assertFalse(needs_classification(guidance.model_dump()))
