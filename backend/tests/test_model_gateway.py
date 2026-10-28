"""Exercise the actual SDK wire format against an in-memory gateway, never paid models."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from routing_guides import analysis_provider, classification_provider, resolution_provider
from routing_guides.analysis_provider import ProviderFailure
from routing_guides.config import Settings
from pydantic import ValidationError
from routing_guides.connections import connection, save_connection, statuses
from routing_guides.model_gateway import compact_gateway_schema, gateway_models, openai_options
from routing_guides.resolution import ResolutionPlan
from routing_guides.resolution_jobs import enable_resolution
from test_assessment import candidate

CONFIG = {'key': 'synthetic-gateway-key', 'model': 'argon-team-alias', 'base_url': 'https://gateway.example.test/v1'}


def response(raw):
    return httpx.Response(200, json={'id':'resp_synthetic', 'object':'response', 'created_at':0,
        'status':'completed', 'model':'argon-upstream-model', 'output':[{'id':'msg_synthetic',
        'type':'message', 'role':'assistant', 'status':'completed',
        'content':[{'type':'output_text', 'text':json.dumps(raw), 'annotations':[]}]}]})


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def test_compact_correction_schema_preserves_structure_and_local_limits(self):
        schema = analysis_provider.strict_schema(ResolutionPlan.model_json_schema())
        compact = compact_gateway_schema(schema)
        self.assertIn('maxItems', schema['properties']['changes'])
        self.assertNotIn('maxItems', compact['properties']['changes'])
        self.assertEqual(compact['required'], schema['required'])
        self.assertFalse(compact['additionalProperties'])
        self.assertEqual(compact['$defs']['SupportedChange']['properties']['field']['enum'],
                         schema['$defs']['SupportedChange']['properties']['field']['enum'])
        with self.assertRaises(ValidationError):
            ResolutionPlan.model_validate({'proposed_spec': None, 'capability_gaps': ['gap'] * 11})

    async def test_extraction_classification_and_preparation_use_only_the_gateway(self):
        current = candidate()
        payloads = {
            'analysis': {'rules':[], 'coverage':[{'page':1,'outcome':'no_rules','note':'No requirements.'}], 'warnings':[]},
            'classification': {'rules':[{'id':current['id'], 'purpose':current['spec']['purpose'],
                'operational_category':current['spec']['operational_category'],
                'consumption_points':current['spec']['consumption_points'], 'reason':'Supported by the source.'}]},
            'preparation': {'proposed_spec':None, 'changes':[], 'questions':[], 'capability_gaps':[]},
        }
        for operation, module in [('analysis',analysis_provider), ('classification',classification_provider), ('preparation',resolution_provider)]:
            requests = []
            def handle(request):
                requests.append(request)
                return response(payloads[operation])
            client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
            with self.subTest(operation=operation), TemporaryDirectory() as folder, \
                    patch.object(module, 'connection', new=AsyncMock(return_value=CONFIG)), \
                    patch('routing_guides.model_gateway.httpx', SimpleNamespace(AsyncClient=lambda **kwargs: client)):
                root = Path(folder)
                saved = root / 'response.json'
                if operation == 'analysis':
                    (root/'page-0.png').write_bytes(b'synthetic-image')
                    result = await module.analyze('litellm', CONFIG['model'], [{'page':1,'text':'Synthetic source'}], '', root, saved)
                    self.assertEqual(result.extraction.rules, [])
                elif operation == 'classification':
                    result = await module.classify('litellm', CONFIG['model'], [current], saved)
                    self.assertEqual(str(result.rules[0].id), current['id'])
                else:
                    result = await module.propose(current, {1:'Synthetic source'}, 'litellm', CONFIG['model'], saved)
                    self.assertIsNone(result.proposed_spec)
                self.assertEqual(len(requests), 1)
                self.assertEqual(str(requests[0].url), CONFIG['base_url']+'/responses')
                self.assertEqual(requests[0].headers['authorization'], 'Bearer '+CONFIG['key'])
                body = json.loads(requests[0].content)
                self.assertEqual(body['model'], CONFIG['model'])
                self.assertFalse(body['store'])
                self.assertTrue(body['text']['format']['strict'])
                if operation == 'analysis':
                    self.assertTrue(any(item['type']=='input_image' for item in body['input'][0]['content']))
                self.assertNotIn(CONFIG['key'], saved.read_text())

    async def test_gateway_rejection_is_sanitized_and_never_falls_back(self):
        requests = []
        def handle(request):
            requests.append(str(request.url))
            return httpx.Response(400, json={'error':{'message':'Unsupported schema '+CONFIG['key'], 'type':'invalid_request_error'}})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with TemporaryDirectory() as folder, patch.object(resolution_provider, 'connection', new=AsyncMock(return_value=CONFIG)), \
                patch('routing_guides.model_gateway.httpx', SimpleNamespace(AsyncClient=lambda **kwargs: client)):
            with self.assertRaises(ProviderFailure) as caught:
                await resolution_provider.propose(candidate(), {1:'Synthetic source'}, 'litellm', CONFIG['model'], Path(folder)/'proposal.json')
            self.assertNotIn(CONFIG['key'], str(caught.exception))
            self.assertEqual(requests, [CONFIG['base_url']+'/responses'])

    async def test_model_discovery_returns_exact_aliases_without_generation(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={'object':'list','data':[{'id':CONFIG['model'], 'object':'model', 'created':0, 'owned_by':'gateway'}]})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        with patch('routing_guides.model_gateway.httpx', SimpleNamespace(AsyncClient=lambda **kwargs: client)):
            self.assertEqual(await gateway_models(CONFIG), [CONFIG['model']])
        self.assertEqual([(r.method,str(r.url)) for r in requests], [('GET',CONFIG['base_url']+'/models')])

    async def test_invalid_gateway_never_uses_a_default_provider_endpoint(self):
        for endpoint in ['', 'http://gateway.example.test/v1', 'https://key@gateway.example.test/v1', 'https://gateway.example.test/v1?key=secret']:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                openai_options('litellm', {**CONFIG,'base_url':endpoint})
        options = openai_options('litellm', CONFIG)
        try:
            self.assertFalse(options['http_client'].follow_redirects)
        finally:
            await options['http_client'].aclose()

    async def test_automatic_preparation_keeps_the_selected_gateway_and_alias(self):
        job = {'pending':[]}
        with patch('routing_guides.resolution_jobs.connection', new=AsyncMock(return_value=CONFIG)) as connect:
            await enable_resolution(job, {'provider':'litellm','model':CONFIG['model']})
        connect.assert_awaited_once_with('litellm')
        self.assertEqual(job['resolution_provider'], 'litellm')
        self.assertEqual(job['resolution_model'], CONFIG['model'])

    async def test_gateway_key_uses_existing_local_and_managed_secret_rules(self):
        with TemporaryDirectory() as folder:
            settings = Settings(database_url='postgresql://unused', storage_root=Path(folder), litellm_api_key='environment-secret')
            with patch('routing_guides.connections.get_settings', return_value=settings), \
                    patch('routing_guides.connections.setting', new=AsyncMock(return_value=CONFIG['model'])), \
                    patch('routing_guides.connections.save_setting', new=AsyncMock()):
                await save_connection('litellm', CONFIG['key'], CONFIG['model'])
                self.assertEqual((await connection('litellm'))['key'], CONFIG['key'])
                self.assertEqual((Path(folder)/'connections.json').stat().st_mode & 0o777, 0o600)
                self.assertNotIn(CONFIG['key'], str(await statuses()))
                settings.credentials_mode = 'environment'
                self.assertEqual((await connection('litellm'))['key'], 'environment-secret')
                with self.assertRaises(ValueError):
                    await save_connection('litellm', 'replacement', CONFIG['model'])
