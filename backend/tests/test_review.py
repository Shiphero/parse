import unittest
from routing_guides.review import compare_rules, individual_review_reasons, duplicate_titles
from test_rules import rule


class ExactComparisonTests(unittest.TestCase):
    def test_page_movement_matches_but_changes_and_duplicates_do_not(self):
        original = rule().model_dump(mode='json')
        old = [{'stable_id': 'old', 'spec': original, 'review': {'actor': 'Original reviewer'}}]
        moved = rule(evidence=[{'page': 2, 'quote': original['evidence'][0]['quote']}]).model_dump(mode='json')
        candidate = {'id': 'new', 'spec': moved}
        self.assertEqual(compare_rules([candidate], old)['unchanged'], {'new': 'old'})
        moved['purpose'] = 'general_guidance'
        self.assertEqual(compare_rules([candidate], old)['unchanged'], {})
        moved['purpose'] = 'shipment_validation'
        moved['assertion']['value'] = 40
        comparison = compare_rules([candidate], old)
        self.assertEqual(comparison['unchanged'], {})
        self.assertEqual(comparison['changed'], {'old': ['new']})
        self.assertEqual(compare_rules([], old)['missing'], ['old'])
        candidate['spec'] = original
        self.assertEqual(compare_rules([candidate, {**candidate, 'id': 'duplicate'}], old)['unchanged'], {})
        self.assertEqual(compare_rules([candidate], old + [{**old[0], 'stable_id': 'duplicate'}])['unchanged'], {})
        candidate['evidence_issues'] = ['Citation mismatch']
        self.assertEqual(compare_rules([candidate], old)['unchanged'], {})

    def test_flags_and_visual_descriptions_cannot_be_bulk_approved_or_carried(self):
        specs = [rule(unresolved_questions=['Which cartons?']), rule(verification='unresolved'),
                 rule(exceptions=[{'description': 'Except promotional items', 'condition': None}]),
                 rule(evidence=[{'page': 1, 'quote': 'Label in lower corner', 'kind': 'visual'}]),
                 rule(evidence=[{'page': 1, 'quote': '50 lb', 'kind': 'text', 'region': [0, 0, .5, .5]}])]
        for spec in specs:
            with self.subTest(spec=spec):
                self.assertTrue(individual_review_reasons(spec))
                serialized = spec.model_dump(mode='json')
                self.assertEqual(compare_rules([{'id': 'new', 'spec': serialized}],
                    [{'stable_id': 'old', 'spec': serialized, 'review': {'actor': 'Reviewer'}}])['unchanged'], {})

    def test_ignored_rules_do_not_create_duplicates_or_change_suggestions(self):
        spec = rule().model_dump(mode='json')
        active = {'id':'active','status':'pending','spec':spec}
        ignored = {'id':'ignored','status':'ignored','spec':spec}
        previous = [{'stable_id':'old','spec':spec,'review':{'actor':'Reviewer'}}]
        self.assertEqual(duplicate_titles([active, ignored]), set())
        self.assertEqual(compare_rules([active, ignored], previous)['unchanged'], {'active':'old'})
        comparison = compare_rules([ignored], previous)
        self.assertEqual(comparison['added'], [])
        self.assertEqual(comparison['missing'], ['old'])
