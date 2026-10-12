import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from routing_guides.analysis_provider import analyze, provider_failure, ProviderFailure
from routing_guides.rules import Extraction
from test_rules import rule


class FakeClient:
    def __init__(self, result):
        self.create = AsyncMock(return_value=result)
        self.messages = SimpleNamespace(create=self.create)
        self.responses = SimpleNamespace(create=self.create)
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return None


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(); self.directory=Path(self.temp.name)
        (self.directory/'page-0.png').write_bytes(b'synthetic image bytes, not a retailer document')
        self.extraction=Extraction(rules=[rule()],coverage=[{'page':1,'outcome':'rules_found','note':'Test'}],warnings=[])
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
