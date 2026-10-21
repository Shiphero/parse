import unittest
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from routing_guides.analysis_provider import analyze, provider_failure, ProviderFailure
from routing_guides.rules import Extraction
from routing_guides.extraction_results import parse_extraction
from pydantic import ValidationError
from test_rules import rule


class FakeStream:
    def __init__(self, create, kwargs):
        self.create, self.kwargs = create, kwargs
    async def __aenter__(self):
        message = await self.create(**self.kwargs)
        return SimpleNamespace(get_final_message=AsyncMock(return_value=message))
    async def __aexit__(self, *args): return None


class FakeClient:
    def __init__(self, result):
        self.create = AsyncMock(return_value=result)
        self.messages = SimpleNamespace(create=self.create, stream=lambda **kwargs: FakeStream(self.create, kwargs))
        self.responses = SimpleNamespace(create=self.create)
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return None


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.directory=Path(self.temp.name)
        (self.directory/'page-0.png').write_bytes(b'synthetic image bytes, not a retailer document')
        self.extraction=Extraction(rules=[rule(schema_version='1.2',verification='unresolved',assertion=None)],coverage=[{'page':1,'outcome':'rules_found','note':'Test'}],warnings=[])
        self.secret=patch('routing_guides.analysis_provider.connection',return_value={'key':'synthetic-key','model':'test'})
        self.secret.start()
    def tearDown(self):self.secret.stop();self.temp.cleanup()

    async def test_claude_receives_text_and_image_and_returns_validated_data(self):
        response=SimpleNamespace(stop_reason='tool_use',content=[SimpleNamespace(type='tool_use',name='submit_extraction',input=self.extraction.model_dump(mode='json'))],model='returned-claude',usage=SimpleNamespace(model_dump=lambda:{'input_tokens':7}))
        client=FakeClient(response)
        with patch('routing_guides.analysis_provider.AsyncAnthropic',return_value=client):
            output=await analyze('anthropic','requested-model',[{'page':1,'text':'50 lb'}],'full context',self.directory)
        self.assertEqual(output.model,'returned-claude')
        request=client.create.call_args.kwargs
        self.assertEqual(request['model'],'requested-model')
        self.assertTrue(any(b['type']=='image' for b in request['messages'][0]['content']))
        self.assertIn('full context',request['messages'][0]['content'][0]['text'])
        self.assertEqual(request['tool_choice'], {'type': 'auto'})
        self.assertEqual(request['tools'][0]['name'], 'submit_extraction')
        # The system prompt and full-document context are cached; per-batch pages follow them.
        self.assertEqual(request['system'][0]['cache_control'], {'type': 'ephemeral'})
        self.assertEqual(request['messages'][0]['content'][0]['cache_control'], {'type': 'ephemeral'})
        self.assertNotIn('Target PDF pages', request['messages'][0]['content'][0]['text'])
        self.assertEqual(request['max_tokens'], 64000)

    async def test_openai_has_images_schema_and_no_stored_response(self):
        response=SimpleNamespace(status='completed',output_text=self.extraction.model_dump_json(),model='returned-openai',usage=None)
        client=FakeClient(response)
        with patch('routing_guides.analysis_provider.AsyncOpenAI',return_value=client):
            output=await analyze('openai','requested-model',[{'page':1,'text':'50 lb'}],'full context',self.directory)
        request=client.create.call_args.kwargs
        self.assertFalse(request['store'])
        self.assertTrue(any(b['type']=='input_image' for b in request['input'][0]['content']))
        self.assertTrue(request['text']['format']['strict'])
        self.assertEqual(len(output.extraction.rules),1)

    async def test_truncation_and_refusal_are_not_complete(self):
        for response in (SimpleNamespace(status='incomplete'),SimpleNamespace(status='completed',output_text='',model='refusal',usage=None)):
            with patch('routing_guides.analysis_provider.AsyncOpenAI',return_value=FakeClient(response)):
                with self.assertRaises(ProviderFailure):
                    await analyze('openai','test',[{'page':1,'text':''}],'context',self.directory)

    async def test_provider_error_does_not_echo_request_or_key(self):
        client=FakeClient(None)
        client.create.side_effect=ValueError('synthetic-key raw provider body')
        with patch('routing_guides.analysis_provider.AsyncAnthropic',return_value=client):
            with self.assertRaises(ProviderFailure) as error:
                await analyze('anthropic','test',[{'page':1,'text':''}],'context',self.directory)
        self.assertNotIn('synthetic-key',str(error.exception))

    async def test_missing_warning_metadata_is_accepted_and_response_is_reused(self):
        raw = self.extraction.model_dump(mode='json')
        del raw['warnings']
        response = SimpleNamespace(stop_reason='tool_use', content=[SimpleNamespace(type='tool_use', name='submit_extraction', input=raw)], model='returned-claude', usage=SimpleNamespace(model_dump=lambda: {'input_tokens': 7}))
        client = FakeClient(response)
        cached = self.directory / 'analysis' / 'batch-1.json'
        with patch('routing_guides.analysis_provider.AsyncAnthropic', return_value=client):
            first = await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], 'context', self.directory, response_path=cached)
            second = await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], 'context', self.directory, response_path=cached)
        self.assertEqual(client.create.await_count, 1)
        self.assertEqual(len(first.extraction.rules), 1)
        self.assertEqual(first.extraction, second.extraction)
        self.assertIn('omitted', first.extraction.warnings[0])
        self.assertNotIn('warnings', json.loads(cached.read_text())['raw'])
        self.assertEqual(cached.stat().st_mode & 0o777, 0o600)
        self.assertEqual(second.usage, {'input_tokens': 7})

    async def test_invalid_rule_response_is_retained_and_reports_field(self):
        raw = self.extraction.model_dump(mode='json')
        del raw['rules'][0]['instruction']
        response = SimpleNamespace(stop_reason='tool_use', content=[SimpleNamespace(type='tool_use', name='submit_extraction', input=raw)], model='returned-claude', usage=SimpleNamespace(model_dump=lambda: {}))
        client = FakeClient(response)
        cached = self.directory / 'analysis' / 'batch-1.json'
        with patch('routing_guides.analysis_provider.AsyncAnthropic', return_value=client):
            for _ in range(2):
                with self.assertRaises(ProviderFailure) as failure:
                    await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], 'context', self.directory, response_path=cached)
                self.assertIn('rules.0.instruction', str(failure.exception))
        self.assertEqual(client.create.await_count, 1)
        self.assertEqual(json.loads(cached.read_text())['raw'], raw)

    async def test_saved_unmapped_proposals_are_recovered_without_provider_call(self):
        from routing_guides.check_catalog import needs_check_mapping
        from routing_guides.evaluator import evaluate_rule
        raw = self.extraction.model_dump(mode='json')
        original = deepcopy(raw['rules'][0])
        raw['rules'] = [original, {**original, 'verification': 'human'},
                        {**original, 'verification': 'external_evidence'},
                        {**original, 'verification': 'data', 'assertion': {
                            'op': 'lte', 'path': 'weight', 'value': 50, 'unit': 'lb'}}]
        cached = self.directory / 'saved-failed-batch.json'
        saved = dict(raw=raw, pages=[1], model='original-model', usage={'input_tokens': 123},
                     prompt_version='routing-extraction-1.9')
        cached.write_text(json.dumps(saved))
        before = cached.read_bytes()
        with patch('routing_guides.analysis_provider.AsyncAnthropic') as client:
            first = await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], '', self.directory, cached)
            second = await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], '', self.directory, cached)
        client.assert_not_called()
        self.assertEqual(first.extraction, second.extraction)
        self.assertEqual(first.model, 'original-model')
        self.assertEqual(first.usage, {'input_tokens': 123})
        self.assertEqual(first.prompt_version, 'routing-extraction-1.9')
        self.assertEqual(cached.read_bytes(), before)
        self.assertEqual(first.extraction.rules[0].model_dump(mode='json'), original)
        self.assertEqual(len(first.extraction.rules), 4)
        self.assertEqual(len(first.extraction.warnings), 3)
        for recovered in first.extraction.rules[1:]:
            self.assertEqual(recovered.verification, 'unresolved')
            self.assertIsNone(recovered.assertion)
            self.assertTrue(needs_check_mapping(recovered))
            self.assertIn('Needs verification mapping', recovered.unresolved_questions[0])
            self.assertEqual(recovered.evidence[0].model_dump(mode='json'), original['evidence'][0])
            self.assertEqual(recovered.instruction, original['instruction'])
            self.assertEqual(evaluate_rule('r', recovered, {'cartons':[{'weight':{'value':40,'unit':'lb'}}]})['outcome'], 'cannot_determine')
        # The public rule contract remains strict outside provider ingestion.
        with self.assertRaises(ValidationError):
            Extraction.model_validate(raw)

    async def test_saved_subject_mismatch_is_recovered_as_unresolved_without_changing_source(self):
        raw = self.extraction.model_dump(mode='json')
        proposal = {**deepcopy(raw['rules'][0]), 'purpose': 'general_guidance',
                    'subject': 'shipment', 'verification': 'human',
                    'operational_category': 'business_administration',
                    'rule_type': {'id': 'billing.requirements', 'version': 1},
                    'placements': [{'workflow': 'billing', 'area': 'billing', 'enabled': True, 'behavior': 'display'}],
                    'consumption_points': ['billing']}
        raw['rules'].append(proposal)
        cached = self.directory / 'saved-subject-mismatch.json'
        cached.write_text(json.dumps(dict(raw=raw, pages=[1], model='original-model',
            usage={'input_tokens': 123}, prompt_version='routing-extraction-1.12')))
        before = cached.read_bytes()
        with patch('routing_guides.analysis_provider.AsyncAnthropic') as client:
            first = await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], '', self.directory, cached)
            second = await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], '', self.directory, cached)
        client.assert_not_called()
        self.assertEqual(cached.read_bytes(), before)
        self.assertEqual(first.extraction, second.extraction)
        self.assertEqual(len(first.extraction.rules), 2)
        self.assertEqual(first.extraction.rules[0], self.extraction.rules[0])
        recovered = first.extraction.rules[1]
        for field in ('instruction', 'subject', 'purpose', 'evidence', 'obligation', 'applicability_text'):
            self.assertEqual(recovered.model_dump(mode='json')[field], proposal[field])
        self.assertIsNone(recovered.rule_type)
        self.assertEqual(recovered.verification, 'unresolved')
        self.assertEqual(recovered.placements, [])
        self.assertEqual(recovered.consumption_points, [])
        self.assertIn('Needs rule type mapping', recovered.unresolved_questions[-1])
        self.assertIn('billing.requirements', first.extraction.warnings[-1])
        with self.assertRaises(ValidationError):
            Extraction.model_validate(raw)
        # Recovery must not swallow other invalid proposals or conflicting checks.
        malformed = deepcopy(raw)
        del malformed['rules'][0]['instruction']
        with self.assertRaises(ValidationError):
            parse_extraction(malformed)
        conflicting = deepcopy(raw)
        conflicting['rules'][1]['assertion'] = {'op': 'lte', 'path': 'weight', 'value': 50, 'unit': 'lb'}
        with self.assertRaises(ValidationError):
            parse_extraction(conflicting)

    async def test_category_conflict_preserves_requirement_and_requires_mapping(self):
        raw = self.extraction.model_dump(mode='json')
        raw['rules'][0].update(purpose='general_guidance', subject='carton',
            operational_category='warehouse_operations',
            rule_type={'id': 'general.guidance', 'version': 1},
            consumption_points=['supplier_management'],
            placements=[{'workflow': 'supplier_management', 'area': 'general_guidance', 'enabled': True, 'behavior': 'display'}])
        original = deepcopy(raw)
        cached = self.directory / 'saved-category-conflict.json'
        cached.write_text(json.dumps(dict(raw=raw, pages=[1], model='original-model',
            usage={}, prompt_version='routing-extraction-1.12')))
        before = cached.read_bytes()
        with patch('routing_guides.analysis_provider.AsyncAnthropic') as client:
            output = await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], '', self.directory, cached)
        client.assert_not_called()
        self.assertEqual(cached.read_bytes(), before)
        recovered = output.extraction.rules[0]
        self.assertEqual(recovered.operational_category, 'warehouse_operations')
        self.assertEqual(recovered.evidence, self.extraction.rules[0].evidence)
        self.assertEqual(recovered.instruction, self.extraction.rules[0].instruction)
        self.assertEqual(recovered.verification, 'unresolved')
        self.assertIsNone(recovered.rule_type)
        self.assertEqual(recovered.placements, [])
        self.assertEqual(recovered.consumption_points, [])
        self.assertIn('general.guidance', recovered.unresolved_questions[-1])
        self.assertIn('operational_category warehouse_operations', output.extraction.warnings[-1])
        self.assertEqual(raw, original)
        with self.assertRaises(ValidationError):
            Extraction.model_validate(raw)
        raw['rules'][0]['evidence'] = []
        with self.assertRaises(ValidationError):
            parse_extraction(raw)

    async def test_saved_coverage_quote_note_is_recovered_without_provider_call(self):
        for quote_note in ('', 'Provider commentary, not verified evidence.'):
            with self.subTest(quote_note=quote_note):
                raw = self.extraction.model_dump(mode='json')
                raw['coverage'][0]['quote_note'] = quote_note
                cached = self.directory / 'saved-coverage-batch.json'
                cached.write_text(json.dumps(dict(raw=raw, pages=[1], model='original-model',
                    usage={'input_tokens': 123}, prompt_version='routing-extraction-1.10')))
                before = cached.read_bytes()
                with patch('routing_guides.analysis_provider.AsyncAnthropic') as client:
                    first = await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], '', self.directory, cached)
                    second = await analyze('anthropic', 'test', [{'page': 1, 'text': '50 lb'}], '', self.directory, cached)
                client.assert_not_called()
                self.assertEqual(first.extraction, second.extraction)
                self.assertEqual(cached.read_bytes(), before)
                self.assertEqual(first.extraction.rules, self.extraction.rules)
                self.assertEqual(first.extraction.coverage[0].note, 'Test' + ('\n' + quote_note if quote_note else ''))
                self.assertEqual(first.extraction.coverage[0].outcome, 'rules_found')
                self.assertIn('quote_note normalized', first.extraction.warnings[0])
                with self.assertRaises(ValidationError):
                    Extraction.model_validate(raw)

    def test_coverage_alias_recovery_remains_strict_and_combines_with_unmapped_recovery(self):
        raw = self.extraction.model_dump(mode='json')
        raw['coverage'][0]['quote_note'] = 'Additional note'
        raw['rules'][0]['verification'] = 'human'
        before = deepcopy(raw)
        recovered = parse_extraction(raw)
        self.assertEqual(raw, before)
        self.assertEqual(recovered.rules[0].verification, 'unresolved')
        self.assertEqual(recovered.coverage[0].note, 'Test\nAdditional note')
        for change in ({'quote_note': None}, {'quote_note': {}}, {'quote_note': 12},
                       {'other_note': ''}, {'page': 0}, {'outcome': 'invented'}, {'note': None}):
            invalid = deepcopy(raw)
            invalid['coverage'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                parse_extraction(invalid)
        missing = deepcopy(raw)
        del missing['coverage'][0]['note']
        with self.assertRaises(ValidationError):
            parse_extraction(missing)
        invalid_rule = deepcopy(raw)
        invalid_rule['rules'][0]['evidence'] = []
        with self.assertRaises(ValidationError):
            parse_extraction(invalid_rule)

    def test_recovery_does_not_hide_other_errors_or_invent_check_mappings(self):
        raw = self.extraction.model_dump(mode='json')
        raw['rules'][0]['verification'] = 'human'
        before = deepcopy(raw)
        parse_extraction(raw)
        self.assertEqual(raw, before)
        for change in ({'standard_check': {'check_id':'invented', 'version':1, 'parameters':{}}},
                       {'instruction': None}, {'evidence': []},
                       {'rule_type': {'id':'invented', 'version':1}}):
            invalid = deepcopy(raw)
            invalid['rules'].append({**raw['rules'][0], **change})
            with self.subTest(change=change), self.assertRaises(ValidationError):
                parse_extraction(invalid)
        invalid = deepcopy(raw)
        invalid['coverage'][0]['page'] = 0
        with self.assertRaises(ValidationError):
            parse_extraction(invalid)

    def test_valid_catalog_and_instruction_only_and_legacy_rules_are_unchanged(self):
        from test_check_catalog import measurement
        from test_delivery import mapped
        manual = mapped(rule_type={'id':'pallet.wrapping','version':1}, subject='pallet',
            verification='human', standard_check=None, consumption_points=['pallet_building'],
            placements=[{'workflow':'pallet_building','area':'wrapping','behavior':'confirm'}])
        raw = Extraction(rules=[measurement(), manual, rule(), rule(purpose='general_guidance')],
                         coverage=[], warnings=['Original warning']).model_dump(mode='json')
        self.assertEqual(parse_extraction(raw).model_dump(mode='json'), raw)

    def test_only_omitted_warnings_are_optional(self):
        for field in ('rules', 'coverage'):
            raw = self.extraction.model_dump(mode='json')
            del raw[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                parse_extraction(raw)
        for warnings in (None, 'not a list'):
            with self.subTest(warnings=warnings), self.assertRaises(ValidationError):
                parse_extraction({**self.extraction.model_dump(mode='json'), 'warnings': warnings})

    def test_only_confirmed_input_limits_split_batches(self):
        for status, message, split, expected in [
            (400, 'tool_choice: type "tool" and "any" are not supported for this model.', False, 'tool settings'),
            (400, 'invalid schema', False, 'schema'),
            (400, 'invalid parameter', False, 'configuration'),
            (400, 'prompt is too long', True, 'input limit'),
            (413, 'request too large', True, 'input limit'),
            (404, 'not found', False, 'model ID'),
            (400, 'credit balance too low', False, 'billing'),
        ]:
            with self.subTest(status=status, message=message):
                exc = Exception('Do not expose request or secrets')
                exc.status_code = status
                exc.body = {'error': {'message': message + ' synthetic-key'}}
                exc.request_id = 'req_diagnostic'
                failure = provider_failure(exc)
                self.assertEqual(failure.split, split)
                self.assertFalse(failure.retryable)
                self.assertIn(expected, str(failure))
                self.assertIn('req_diagnostic', str(failure))
                self.assertNotIn('synthetic-key', str(failure))

    async def test_claude_plain_text_or_truncated_tool_is_not_accepted(self):
        for reason in ('end_turn', 'max_tokens'):
            response = SimpleNamespace(stop_reason=reason, content=[SimpleNamespace(type='text', text='Not structured rules')])
            with patch('routing_guides.analysis_provider.AsyncAnthropic', return_value=FakeClient(response)):
                with self.assertRaises(ProviderFailure) as error:
                    await analyze('anthropic', 'test', [{'page': 1, 'text': ''}], 'context', self.directory)
            self.assertEqual(error.exception.split, reason == 'max_tokens')
