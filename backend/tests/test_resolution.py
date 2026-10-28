"""Source-backed preparation contracts; synthetic text and mocked paid providers."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import ValidationError
from routing_guides import resolution_provider as provider
from routing_guides.resolution import ResolutionPlan, resolve_plan, validate_plan
from routing_guides.rules import RuleSpec
from routing_guides.evaluator import evaluate_rule
from routing_guides.review import individual_review_reasons
from test_assessment import candidate

PAGES = {1: 'Cartons must not exceed 50 lb. Applies to every carton.'}


def proposal(current, **changes):
    return ResolutionPlan(proposed_spec=RuleSpec.model_validate({**current['spec'], **changes}),
        changes=[{'field': key, 'explanation': 'The source explicitly states this requirement.',
                  'sources': [{'page': 1, 'quote': PAGES[1]}]} for key in changes])


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.rule = candidate()

    def test_automatic_duplicates_require_identical_definitions_and_valid_sources(self):
        from routing_guides.automatic_review import duplicate_key
        other = deepcopy(self.rule)
        other['spec']['evidence'][0]['page'] = 2
        pages = {1: PAGES[1], 2: PAGES[1]}
        self.assertEqual(duplicate_key(self.rule, pages), duplicate_key(other, pages))
        other['spec']['applicability_text'] = 'Only international shipments'
        self.assertNotEqual(duplicate_key(self.rule, pages), duplicate_key(other, pages))
        other['spec']['evidence'][0]['quote'] = 'Unsupported quotation'
        self.assertIsNone(duplicate_key(other, pages))
        other = deepcopy(self.rule)
        other['source_guide_id'] = 'another-edition'
        self.assertNotEqual(duplicate_key(self.rule, pages), duplicate_key(other, pages))

    def resolve(self, plan, verdicts=None):
        return resolve_plan(self.rule, plan, verdicts if verdicts is not None else {c.field: True for c in plan.changes},
                            PAGES, 'anthropic', 'test', 'fingerprint')

    def test_verified_change_keeps_original_evidence_and_records_before_after(self):
        before = deepcopy(self.rule)
        plan = proposal(self.rule, instruction='Cartons must not exceed 50 lb.')
        spec, record = self.resolve(plan)
        self.assertEqual(self.rule, before)
        self.assertEqual(spec['evidence'], before['spec']['evidence'])
        self.assertEqual(record.revision, 2)
        self.assertEqual(record.changes[0].before, before['spec']['instruction'])
        self.assertEqual(record.changes[0].after, spec['instruction'])
        self.assertTrue(record.changes[0].applied)
        self.assertEqual(self.rule['status'], 'pending')

    def test_partial_verification_does_not_apply_an_inconsistent_subset(self):
        plan = proposal(self.rule, instruction='Cartons must not exceed 50 lb.', applicability_text='Applies to every carton.')
        spec, record = self.resolve(plan, {'instruction': True, 'applicability_text': False})
        self.assertEqual(spec, self.rule['spec'])
        self.assertEqual(record.revision, 1)
        self.assertTrue(record.changes[0].verified)
        self.assertFalse(any(c.applied for c in record.changes))

    def test_verified_existing_check_parameters_can_be_corrected_without_enforcement(self):
        binding = deepcopy(self.rule['spec']['standard_check'])
        binding['parameters']['threshold'] = 40
        spec, record = self.resolve(proposal(self.rule, standard_check=binding))
        self.assertEqual(spec['standard_check'], binding)
        self.assertTrue(record.changes[0].applied)

    def test_existing_enforcement_still_requires_a_decision(self):
        self.rule['spec']['placements'][0]['behavior'] = 'block'
        plan = proposal(self.rule, instruction='Cartons must not exceed 50 lb.')
        spec, record = self.resolve(plan)
        self.assertEqual(spec, self.rule['spec'])
        self.assertFalse(record.changes[0].applied)

    def test_missing_mapping_can_be_filled_without_changing_obligation(self):
        complete = deepcopy(self.rule['spec'])
        self.rule['spec'] = RuleSpec.model_validate({**complete, 'rule_type': None, 'placements': [],
            'standard_check': None, 'verification': 'unresolved'}).model_dump(mode='json')
        plan = proposal(self.rule, **{key: complete[key] for key in ('rule_type', 'placements', 'standard_check', 'verification')})
        spec, record = self.resolve(plan)
        self.assertEqual(spec, complete)
        self.assertTrue(all(c.applied for c in record.changes))

    def test_missing_explanation_bad_quote_or_removed_evidence_rejects_whole_plan(self):
        valid = proposal(self.rule, instruction='Cartons must not exceed 50 lb.')
        missing = valid.model_copy(deep=True)
        missing.changes = []
        bad_quote = valid.model_copy(deep=True)
        bad_quote.changes[0].sources[0].quote = 'Fabricated source'
        removed = proposal(self.rule, evidence=[{'page': 1, 'quote': PAGES[1]}])
        for plan in (missing, bad_quote, removed):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                validate_plan(self.rule['spec'], plan, PAGES)

    def test_reference_requirement_can_be_reviewed_but_never_claims_compliance(self):
        from test_rules import rule
        from test_delivery import mapped
        from routing_guides.delivery import subjects_for
        reference = rule(schema_version='1.2', assertion=None, verification='unresolved', execution_mode='reference_only')
        self.assertFalse(individual_review_reasons(reference))
        result = evaluate_rule('r', reference, {'cartons': [{'weight': {'value': 30, 'unit': 'lb'}}]})
        self.assertEqual(result['outcome'], 'cannot_determine')
        placed = mapped(standard_check=None, verification='unresolved', execution_mode='reference_only',
            placements=[{'workflow': 'mobile_packing', 'area': 'carton_selection', 'behavior': 'display'}])
        delivered = subjects_for(placed, placed.placements[0], {'cartons': [{'id': 'carton'}]})
        self.assertEqual(delivered[0].action, 'needs_information')
        self.assertIsNone(delivered[0].check_outcome)
        for behavior in ('confirm', 'warn', 'block'):
            with self.subTest(behavior=behavior), self.assertRaises(ValidationError):
                RuleSpec.model_validate({**placed.model_dump(mode='json'), 'placements': [
                    {'workflow': 'mobile_packing', 'area': 'carton_selection', 'behavior': behavior}]})
        for changes in ({'purpose': 'general_guidance'}, {'verification': 'human'},
                        {'standard_check': self.rule['spec']['standard_check']},
                        {'assertion': {'op': 'eq', 'path': 'x', 'value': 1}}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                RuleSpec.model_validate({**reference.model_dump(mode='json'), **changes})


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_verification_is_cached_and_never_applies_unverified_changes(self):
        current = candidate()
        plan = proposal(current, instruction='Cartons must not exceed 50 lb.')
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = httpx.Response(200, json={'answers': {'instruction': {
            'type': 'choice', 'choice': 'supported', 'confidence': 0.99,
            'probabilities': {'supported': 0.8, 'unsupported': 0.2}}}})
        with TemporaryDirectory() as directory, patch.object(provider.httpx, 'AsyncClient', return_value=client), \
                patch.object(provider, 'connection', return_value={'key': 'test-private-key', 'model': 'test'}):
            path = Path(directory) / 'verification.json'
            first = await provider.verify_changes(current, plan, PAGES, 'test', path)
            second = await provider.verify_changes(current, plan, PAGES, 'test', path)
            self.assertEqual(first, {'instruction': False})
            self.assertEqual(second, first)
            client.post.assert_awaited_once()
            self.assertNotIn('test-private-key', path.read_text())
            path.write_text('{invalid')
            with self.assertRaises(provider.AssessmentResponseError):
                await provider.verify_changes(current, plan, PAGES, 'test', path)
            client.post.assert_awaited_once()

    async def test_preparation_reuses_retained_provider_output_and_validates_citations(self):
        current = candidate()
        plan = proposal(current, instruction='Cartons must not exceed 50 lb.')
        from types import SimpleNamespace
        result = SimpleNamespace(content=[SimpleNamespace(type='tool_use', name='resolution_plan', input=plan.model_dump(mode='json'))],
            stop_reason='tool_use', usage=SimpleNamespace(model_dump=lambda: {'input_tokens': 10}))
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.messages.create.return_value = result
        with TemporaryDirectory() as directory, patch.object(provider, 'AsyncAnthropic', return_value=client), \
                patch.object(provider, 'connection', return_value={'key': 'test-private-key', 'model': 'test'}):
            path = Path(directory) / 'proposal.json'
            first = await provider.propose(current, PAGES, 'anthropic', 'test', path)
            second = await provider.propose(current, PAGES, 'anthropic', 'test', path)
            self.assertEqual(first, second)
            client.messages.create.assert_awaited_once()
            self.assertNotIn('test-private-key', path.read_text())
            with self.assertRaises(provider.AssessmentResponseError):
                await provider.propose(current, {1: 'Different source'}, 'anthropic', 'test', path)


    async def test_malformed_proposal_gets_one_forced_tool_repair_and_keeps_both_responses(self):
        from types import SimpleNamespace
        current = candidate()
        good = ResolutionPlan(proposed_spec=None).model_dump(mode='json')
        def result(raw):
            return SimpleNamespace(content=[SimpleNamespace(type='tool_use', name='resolution_plan', input=raw)],
                stop_reason='tool_use', usage=SimpleNamespace(model_dump=lambda: {'input_tokens':10}))
        client = AsyncMock()
        client.__aenter__.return_value=client
        client.messages.create.side_effect=[result({'proposed_spec':{'instruction':'invalid-secret-input'}}),result(good)]
        with TemporaryDirectory() as directory, patch.object(provider,'AsyncAnthropic',return_value=client), \
                patch.object(provider,'connection',return_value={'key':'test-private-key','model':'test'}):
            path=Path(directory)/'proposal.json'
            output=await provider.propose(current,PAGES,'anthropic','test',path)
            self.assertIsNone(output.proposed_spec)
            self.assertEqual(client.messages.create.await_count,2)
            self.assertEqual(client.messages.create.call_args.kwargs['tool_choice']['type'],'tool')
            self.assertTrue(path.with_suffix('.repair.json').exists())
            await provider.propose(current,PAGES,'anthropic','test',path)
            self.assertEqual(client.messages.create.await_count,2)

    async def test_failed_repair_reports_safe_fields_without_exposing_values(self):
        from types import SimpleNamespace
        result=SimpleNamespace(content=[SimpleNamespace(type='tool_use',name='resolution_plan',input={
            'proposed_spec':{'instruction':'private-source-sentinel'}})],stop_reason='tool_use',
            usage=SimpleNamespace(model_dump=lambda:{}))
        client=AsyncMock()
        client.__aenter__.return_value=client
        client.messages.create.return_value=result
        with TemporaryDirectory() as directory, patch.object(provider,'AsyncAnthropic',return_value=client), \
                patch.object(provider,'connection',return_value={'key':'secret-key','model':'test'}):
            with self.assertRaises(provider.ResolutionResponseError) as caught:
                await provider.propose(candidate(),PAGES,'anthropic','test',Path(directory)/'proposal.json')
            self.assertEqual(caught.exception.code,'invalid_structure')
            self.assertNotIn('private-source-sentinel',str(caught.exception))
            self.assertNotIn('secret-key',str(caught.exception))
            self.assertEqual(client.messages.create.await_count,2)
