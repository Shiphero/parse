import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx

from routing_guides import classification_provider, jev_classification as jev
from routing_guides.analysis_provider import ProviderFailure
from routing_guides.classification_mapping import apply_classification
from routing_guides.connections import connection, save_connection, statuses
from routing_guides.config import Settings
from test_rules import rule


def response_for(questions, unmapped=False):
    choices = {'purpose': 'shipment_validation', 'category': 'warehouse_operations',
               'rule_type': 'unmapped' if unmapped else 'carton.measurement'}
    answers = {}
    for name, question in questions.items():
        selected = choices.get(name, 'yes' if name == 'workflow:mobile_packing' else 'uncertain')
        answers[name] = {'type': 'choice', 'choice': selected, 'confidence': 1.0,
                         'probabilities': {option: float(option == selected) for option in question['criteria']}}
    return {'model': 'jev-1.14.0', 'answers': answers, 'usage': {'input_tokens': 100, 'output_tokens': 30}}


class JevClassificationTests(unittest.IsolatedAsyncioTestCase):
    def candidate(self):
        return {'id': str(uuid4()), 'spec': rule().model_dump(mode='json')}

    def test_unmapped_and_uncertain_choices_do_not_force_assignments(self):
        questions = jev.questions()
        result = jev.normalize(self.candidate(), response_for(questions, unmapped=True), questions)
        self.assertIsNone(result['rule_type'])
        self.assertEqual(result['consumption_points'], ['mobile_packing'])
        self.assertIn('No compatible catalog type', result['reason'])

    def test_missing_unknown_and_invalid_probability_answers_fail_closed(self):
        questions = jev.questions()
        valid = response_for(questions)
        missing = deepcopy(valid)
        del missing['answers']['purpose']
        unknown = deepcopy(valid)
        unknown['answers']['rule_type']['choice'] = 'invented'
        invalid = deepcopy(valid)
        invalid['answers']['purpose']['confidence'] = float('nan')
        for response in (missing, unknown, invalid):
            with self.subTest(response=response), self.assertRaises(ProviderFailure):
                jev.normalize(self.candidate(), response, questions)

    def test_weak_type_choice_is_not_converted_into_a_catalog_assignment(self):
        questions = jev.questions()
        raw = response_for(questions)
        answer = raw['answers']['rule_type']
        answer['confidence'] = .6
        answer['probabilities'].update({'carton.measurement': .6, 'unmapped': .4})
        result = jev.normalize(self.candidate(), raw, questions)
        self.assertIsNone(result['rule_type'])

    async def test_adapter_saves_typed_answers_and_preserves_verification(self):
        candidate = self.candidate()
        client = AsyncMock()
        client.__aenter__.return_value = client
        payload = response_for(jev.questions())
        client.post.return_value = httpx.Response(200, json=payload)
        with TemporaryDirectory() as folder, patch.object(jev.httpx, 'AsyncClient', return_value=client), \
                patch.object(classification_provider, 'connection', return_value={'key': 'synthetic-key', 'model': 'jev-1.14.0'}):
            path = Path(folder) / 'response.json'
            output = await classification_provider.classify('jev', 'jev-1.14.0', [candidate], path)
            await classification_provider.classify('jev', 'jev-1.14.0', [candidate], path)
            client.post.assert_awaited_once()
            self.assertIn('provider_responses', path.read_text())
            self.assertNotIn('synthetic-key', path.read_text())
            updated, _ = apply_classification(candidate['spec'], output.rules[0])
            for name in ('instruction', 'verification', 'standard_check', 'evidence', 'assertion'):
                self.assertEqual(updated.get(name), candidate['spec'].get(name))
            request = client.post.call_args
            self.assertEqual(request.args[0], jev.ENDPOINT)
            self.assertEqual(request.kwargs['json']['model'], 'jev-1.14.0')

    async def test_auth_failure_hides_provider_response_body(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = httpx.Response(401, text='sensitive-provider-response')
        with patch.object(jev.httpx, 'AsyncClient', return_value=client):
            with self.assertRaises(ProviderFailure) as raised:
                await jev.classify_jev('synthetic-key', 'jev-1.14.0', [self.candidate()])
        self.assertIn('Check the API key', str(raised.exception))
        self.assertNotIn('sensitive-provider-response', str(raised.exception))

    async def test_jev_credentials_are_masked_preserved_and_removable(self):
        with TemporaryDirectory() as folder:
            settings = Settings(database_url='postgresql://unused', storage_root=Path(folder),
                                jev_api_key='environment-key')
            with patch('routing_guides.connections.get_settings', return_value=settings), \
                 patch('routing_guides.connections.setting', new=AsyncMock(return_value='jev-preview')), \
                 patch('routing_guides.connections.save_setting', new=AsyncMock()):
                self.assertEqual((await connection('jev'))['key'], 'environment-key')
                await save_connection('jev', 'synthetic-key', 'jev-1.14.0')
                await save_connection('jev', None, 'jev-preview')
                self.assertEqual((await connection('jev'))['key'], 'synthetic-key')
                self.assertNotIn('synthetic-key', str(await statuses()))
                self.assertEqual((Path(folder) / 'connections.json').stat().st_mode & 0o777, 0o600)
                await save_connection('jev', '', 'jev-preview')
                self.assertEqual((await connection('jev'))['key'], '')
