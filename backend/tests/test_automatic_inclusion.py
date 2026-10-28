"""Automation boundaries: retain real requirements, preserve originals and human decisions."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from routing_guides.assessment import PROMPT_VERSION, assessment_fingerprint
from routing_guides.automatic_review import can_set_aside_non_rule, set_aside_non_rules
from routing_guides.classification_mapping import needs_auto_classification
from routing_guides.classification_provider import Classification, ClassifiedOutput
from routing_guides.resolution_provider import propose
from routing_guides.resolution import preparation_targets, resolve_plan
from routing_guides.review_processing import resolution_context
from test_assessment import candidate
from test_rules import rule

PAGES = {1: 'Cartons must not exceed 50 lb.'}


def assessed():
    current = candidate()
    job = {'id': 'test-job', 'actor': 'Reviewer', 'auto_process': True,
           'selected_revisions': [{'id': current['id'], 'revision': current['revision']}]}
    current['assessment'] = {'inclusion': 'not_a_rule', 'inclusion_confidence': .99,
        'job_id': job['id'], 'prompt_version': PROMPT_VERSION,
        'fingerprint': assessment_fingerprint(current, []), 'resolution_fingerprint': resolution_context(current),
        'dimensions': [{'name': 'source_accuracy', 'choice': 'supported', 'confidence': .99,
                        'probabilities': {'supported': .99}}]}
    return current, job


class InclusionTests(unittest.IsolatedAsyncioTestCase):
    def test_requirements_guidance_uncertainty_and_low_confidence_are_never_excluded(self):
        current, job = assessed()
        self.assertTrue(can_set_aside_non_rule(current, job, [], PAGES))
        for choice, confidence in [('requirement', 1), ('guidance', 1), ('uncertain', 1), ('not_a_rule', .97)]:
            changed = deepcopy(current)
            changed['assessment'].update(inclusion=choice, inclusion_confidence=confidence)
            self.assertFalse(can_set_aside_non_rule(changed, job, [], PAGES))

    def test_stale_results_missing_sources_and_human_decisions_block_exclusion(self):
        current, job = assessed()
        for update in [{'review': {'actor': 'Human'}}, {'automation_hold': True}, {'revision': 2},
                       {'status': 'approved'}, {'evidence_issues': ['Source mismatch']}]:
            self.assertFalse(can_set_aside_non_rule({**current, **update}, job, [], PAGES))
        self.assertFalse(can_set_aside_non_rule(current, {**job, 'auto_process': False}, [], PAGES))
        self.assertFalse(can_set_aside_non_rule(current, job, [], {1: 'Different source text'}))
        self.assertFalse(can_set_aside_non_rule(current, job, [], {}))
        current['assessment']['dimensions'][0]['choice'] = 'uncertain'
        self.assertFalse(can_set_aside_non_rule(current, job, [], PAGES))

    async def test_exclusion_preserves_definition_and_audits_original(self):
        current, job = assessed()
        before = deepcopy(current)
        data = {'rules': [current], 'assessment_job': job}
        events = []
        session = SimpleNamespace(add=events.append)
        with patch('routing_guides.automatic_review.source_pages', new=AsyncMock(return_value=PAGES)):
            await set_aside_non_rules(session, SimpleNamespace(id='run'), data, {})
        self.assertEqual(current['status'], 'ignored')
        self.assertEqual(current['review']['mode'], 'automatic_non_rule')
        self.assertEqual(current['spec'], before['spec'])
        self.assertEqual(current['revision'], before['revision'])
        self.assertEqual(events[0].payload['before'], before)
        self.assertEqual(job['non_rules_removed'], 1)

    async def test_jev_completes_classification_without_a_generative_call(self):
        text = 'Consult the supplier guide for reference.'
        current = candidate(spec=rule(schema_version='1.2', purpose='general_guidance', verification='human',
            assertion=None, operational_category='unclassified', consumption_points=[],
            instruction=text, evidence=[{'page': 1, 'quote': text}]).model_dump(mode='json'))
        classified = Classification(id=current['id'], purpose='general_guidance',
            operational_category='business_administration', consumption_points=['supplier_management'],
            rule_type={'id': 'general.guidance', 'version': 1}, reason='Reference instructions for supplier management.')
        before = deepcopy(current)
        with TemporaryDirectory() as folder, patch('routing_guides.classification_provider.classify',
                new=AsyncMock(return_value=ClassifiedOutput([classified], 'jev-test', {}))) as classify, \
                patch('routing_guides.resolution_provider.proposal_response', new=AsyncMock()) as generate:
            plan = await propose(current, {1: text}, 'anthropic', 'unused', Path(folder)/'plan.json', 'jev-test')
        classify.assert_awaited_once()
        generate.assert_not_awaited()
        self.assertEqual(current, before)
        self.assertFalse(preparation_targets({**current, 'spec': plan.proposed_spec.model_dump(mode='json')}))
        unchanged, record = resolve_plan(current, plan, {}, {1: text}, 'anthropic', 'unused', 'fingerprint')
        self.assertEqual(unchanged, current['spec'])
        self.assertFalse(any(change.applied for change in record.changes))
        updated, record = resolve_plan(current, plan, {c.field: True for c in plan.changes},
                                       {1: text}, 'anthropic', 'unused', 'fingerprint')
        self.assertEqual(updated['rule_type']['id'], 'general.guidance')
        self.assertTrue(all(c.applied for c in record.changes))

    def test_reference_only_with_complete_classification_is_not_missing_a_type(self):
        spec = candidate()['spec']
        spec.update(rule_type=None, execution_mode='reference_only')
        self.assertFalse(needs_auto_classification(spec))
        spec['consumption_points'] = []
        self.assertTrue(needs_auto_classification(spec))
