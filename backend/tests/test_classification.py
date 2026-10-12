import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from routing_guides import classification_provider as provider
from routing_guides.analysis_provider import ProviderFailure
from test_rules import rule


class ClassificationProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_output_requires_exact_unique_ids_and_known_purpose(self):
        rid = str(uuid4())
        good = {'id': rid, 'purpose': 'general_guidance', 'reason': 'Supplier contact maintenance is ongoing administration.'}
        self.assertEqual(provider.parse_classifications({'rules': [good]}, [rid])[0].purpose, 'general_guidance')
        for value in [{'rules': []}, {'rules': [good, good]}, {'rules': [{**good, 'id': str(uuid4())}]}]:
            with self.assertRaises(ProviderFailure):
                provider.parse_classifications(value, [rid])

    async def test_text_only_classification_retains_valid_output_and_does_not_repeat_call(self):
        rid = str(uuid4())
        candidate = {'id': rid, 'spec': rule(title='Maintain current contact information with Ulta', instruction='Keep brand partner contacts current.').model_dump(mode='json')}
        raw = {'rules': [{'id': rid, 'purpose': 'general_guidance', 'reason': 'Ongoing supplier administration, not an individual shipment check.'}]}
        response = SimpleNamespace(stop_reason='tool_use', content=[SimpleNamespace(type='tool_use', name='classify_rules', input=raw)], model='test-returned-model', usage=SimpleNamespace(model_dump=lambda: {'input_tokens': 100}))
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.messages.create.return_value = response
        with TemporaryDirectory() as tmp, patch.object(provider, 'connection', return_value={'key': 'synthetic', 'model': 'test'}), patch.object(provider, 'AsyncAnthropic', return_value=client):
            path = Path(tmp) / 'batch.json'
            output = await provider.classify('anthropic', 'test', [candidate], path)
            again = await provider.classify('anthropic', 'test', [candidate], path)
            self.assertEqual(output.rules[0].purpose, 'general_guidance')
            self.assertEqual(again.model, 'test-returned-model')
            self.assertEqual(client.messages.create.await_count, 1)
            arguments = client.messages.create.call_args.kwargs
            self.assertIn('Maintain current contact information with Ulta', arguments['system'])
            self.assertIsInstance(arguments['messages'][0]['content'], str)
            self.assertEqual(arguments['tool_choice'], {'type': 'auto'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
