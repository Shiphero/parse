"""Content comparisons are navigation hints, not approval decisions."""
import unittest
from routing_guides.guide_versions import compare_editions


class EditionComparisonTests(unittest.TestCase):
    def test_page_movement_is_unchanged_without_inheriting_approval(self):
        spec = {'title': 'Pack separately', 'subject': 'carton', 'instruction': 'One PO per carton.'}
        previous = [{'stable_id': 'old', 'spec': {**spec, 'evidence': [{'page': 1}]}, 'review': None}]
        current = [{'id': 'new', 'status': 'pending', 'spec': {**spec, 'evidence': [{'page': 7}]}}]
        self.assertEqual(compare_editions(current, previous)['unchanged'], {'new': 'old'})
        self.assertEqual(current[0]['status'], 'pending')

    def test_changed_added_missing_and_ambiguous_matches(self):
        def spec(title, instruction):
            return {'title': title, 'subject': 'carton', 'instruction': instruction}
        previous = [{'stable_id': 'a', 'spec': spec('Weight', '50 lb')},
                    {'stable_id': 'b', 'spec': spec('Old', 'Old rule')}]
        current = [{'id': 'c', 'status': 'pending', 'spec': spec('Weight', '40 lb')},
                   {'id': 'd', 'status': 'pending', 'spec': spec('New', 'New rule')}]
        comparison = compare_editions(current, previous)
        self.assertEqual(comparison['changed'], {'a': ['c']})
        self.assertEqual(comparison['added'], ['d'])
        self.assertEqual(comparison['missing'], ['b'])
        current.append({'id': 'e', 'status': 'pending', 'spec': spec('Weight', '40 lb')})
        self.assertEqual(compare_editions(current, previous)['unchanged'], {})
