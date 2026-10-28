"""Assessment preview contracts use synthetic sources and mocked provider calls."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
import httpx
from routing_guides import assessment_provider as provider
from routing_guides.analysis_provider import ProviderFailure
from routing_guides.assessment import choose_sample, duplicate_index, related_rules
from routing_guides.assessment_api import StartAssessment, prepare_job
from routing_guides.workflow_api import RunPayload
from test_delivery import mapped


def candidate(**changes):
    spec = mapped(placements=[{'workflow': 'mobile_packing', 'area': 'carton_selection', 'behavior': 'display'}]).model_dump(mode='json')
    return {'id': str(uuid4()), 'revision': 1, 'status': 'pending', 'source_guide_id': str(uuid4()),
            'review': None, 'evidence_issues': [], 'spec': spec, **changes}


def response(related=(), duplicate_choice='distinct'):
    payload = {'model': 'jev-test', 'usage': {'input_tokens': 100, 'output_tokens': 20},
            'answers': {name: {'type': 'choice', 'choice': 'supported', 'confidence': 0.99,
                              'probabilities': {'supported': 0.99, 'correction': 0.005, 'uncertain': 0.005}}
                        for name in provider.DIMENSIONS}}
    payload['answers']['automatic_approval'] = {'type': 'choice', 'choice': 'supported', 'confidence': 0.99,
                                               'probabilities': {'supported': 0.99, 'unsupported': 0.01}}
    payload['answers']['inclusion'] = {'type': 'choice', 'choice': 'requirement', 'confidence': 0.99,
        'probabilities': {'requirement': 0.99, 'guidance': 0.005, 'not_a_rule': 0.002, 'uncertain': 0.003}}
    for rule in related:
        payload['answers'][f'duplicate:{rule["id"]}'] = {
            'type': 'choice', 'choice': duplicate_choice, 'confidence': 0.99,
            'probabilities': {choice: 1.0 if choice == duplicate_choice else 0.0 for choice in provider.DUPLICATE_CHOICES}}
    return payload


class AssessmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / 'response.json'
        self.rule = candidate()
        self.pages = {1: 'Cartons must not exceed 50 lb.', 2: 'Additional packaging guidance.'}
        self.client = AsyncMock()
        self.client.__aenter__.return_value = self.client
        self.client.post.return_value = httpx.Response(200, json=response())
        self.patches = [patch.object(provider.httpx, 'AsyncClient', return_value=self.client),
                        patch.object(provider, 'connection', return_value={'key': 'private-test-key', 'model': 'jev-test'})]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def assess(self, related=None):
        return await provider.assess(self.rule, related or [], self.pages, 'jev-test', self.path, 'job-1')

    async def test_ready_preview_preserves_rule_and_reuses_source_aware_response(self):
        before = deepcopy(self.rule)
        first = await self.assess()
        saved = self.path.read_bytes()
        second = await self.assess()
        self.assertEqual(first.outcome, 'ready')
        self.assertEqual(second.dimensions, first.dimensions)
        self.assertEqual(self.rule, before)
        self.assertEqual(self.path.read_bytes(), saved)
        self.client.post.assert_awaited_once()
        request = self.client.post.call_args.kwargs['json']
        self.assertEqual(request['state']['rule']['exceptions'], before['spec']['exceptions'])
        self.assertEqual(request['state']['source_pages'][0]['text'], self.pages[1])
        self.assertEqual(request['state']['source_pages'][1]['page'], 2)
        self.assertNotIn('private-test-key', saved.decode())
        self.assertEqual(first.usage, {'input_tokens': 100, 'output_tokens': 20})

    async def test_inclusion_keeps_guidance_and_never_approves_non_rules(self):
        for choice in ('guidance', 'not_a_rule', 'uncertain'):
            self.path.unlink(missing_ok=True)
            raw = response()
            raw['answers']['inclusion'] = {'type': 'choice', 'choice': choice, 'confidence': 1.0,
                'probabilities': {key: float(key == choice) for key in provider.INCLUSION_CHOICES}}
            self.client.post.return_value = httpx.Response(200, json=raw)
            output = await self.assess()
            self.assertEqual(output.inclusion, choice)
            self.assertEqual(output.auto_approval_supported, choice == 'guidance')

    async def test_high_confidence_cannot_override_source_or_duplicate_issues(self):
        peer = candidate(spec=deepcopy(self.rule['spec']))
        self.rule['spec']['evidence'][0]['quote'] = 'Invented source quotation'
        self.client.post.return_value = httpx.Response(200, json=response([peer], 'duplicate'))
        result = await self.assess([peer])
        self.assertEqual(result.outcome, 'needs_correction')
        self.assertIn('source_mismatch', [i.code for i in result.issues])
        duplicate = next(i for i in result.issues if i.code == 'duplicate_duplicate')
        self.assertEqual(duplicate.related_rule_ids, [peer['id']])
        self.assertIn('PDF pages 1', duplicate.action)

    def test_cross_title_candidate_search_finds_matching_instructions_and_numeric_conflicts(self):
        match = candidate(spec=deepcopy(self.rule['spec']))
        match['spec']['title'] = 'Maximum package weight'
        conflict = candidate(spec=deepcopy(self.rule['spec']))
        conflict['spec']['title'] = 'Maximum allowed carton mass'
        conflict['spec']['instruction'] = 'Keep carton weight at or below 40 lb.'
        unrelated = candidate(spec=deepcopy(self.rule['spec']))
        unrelated['spec'].update(title='Electronic transmission timing', instruction='Send advance shipping notices before dispatch.')
        ignored = candidate(status='ignored', spec=deepcopy(self.rule['spec']))
        matches = related_rules(self.rule, duplicate_index([self.rule, match, conflict, unrelated, ignored]))
        self.assertEqual({r['id'] for r in matches}, {match['id'], conflict['id']})

    async def test_jev_distinguishes_duplicates_distinct_scope_conflicts_and_uncertainty(self):
        peer = candidate(spec=deepcopy(self.rule['spec']))
        peer['spec']['title'] = 'Maximum package weight'
        original = deepcopy(peer)
        for choice in provider.DUPLICATE_CHOICES:
            with self.subTest(choice=choice):
                self.path = Path(self.temp.name) / f'{choice}.json'
                self.client.post.return_value = httpx.Response(200, json=response([peer], choice))
                result = await self.assess([peer])
                self.assertEqual(result.duplicates[0].choice, choice)
                self.assertEqual(result.duplicates[0].rule_id, peer['id'])
                self.assertEqual(result.duplicate_candidates, 1)
                self.assertEqual(result.outcome, 'ready' if choice == 'distinct' else 'needs_review')
                if choice != 'distinct':
                    self.assertEqual(result.issues[-1].related_rule_ids, [peer['id']])
                self.assertEqual(peer, original)
                self.assertEqual(self.rule['status'], 'pending')
        request = self.client.post.call_args.kwargs['json']
        self.assertEqual(request['state']['similar_rule_candidates'][0]['spec']['exceptions'], peer['spec']['exceptions'])
        self.assertIn('numeric thresholds', request['questions'][f'duplicate:{peer["id"]}']['instructions'])

    async def test_missing_pair_answer_cannot_be_treated_as_distinct(self):
        peer = candidate()
        with self.assertRaises(ProviderFailure):
            await self.assess([peer])
        self.assertTrue(self.path.exists())

    async def test_distinct_comparison_is_not_blocked_by_a_second_confidence_score(self):
        peer = candidate()
        payload = response([peer])
        payload['answers'][f'duplicate:{peer["id"]}']['confidence'] = 0.6
        self.client.post.return_value = httpx.Response(200, json=payload)
        result = await self.assess([peer])
        self.assertEqual(result.outcome, 'ready')
        self.assertTrue(result.auto_approval_supported)

    async def test_additional_duplicate_batches_are_checked_and_cached(self):
        peers = [candidate() for _ in range(provider.MAX_DUPLICATE_COMPARISONS + 1)]
        extra = response(peers[provider.MAX_DUPLICATE_COMPARISONS:])
        extra['answers'] = {key: value for key, value in extra['answers'].items() if key.startswith('duplicate:')}
        self.client.post.side_effect = [httpx.Response(200, json=response(peers[:provider.MAX_DUPLICATE_COMPARISONS])),
                                       httpx.Response(200, json=extra)]
        result = await self.assess(peers)
        self.assertEqual(result.outcome, 'ready')
        self.assertEqual(result.duplicate_candidates, len(peers))
        self.assertEqual(len(result.duplicates), len(peers))
        self.assertEqual(result.usage, {'input_tokens': 200, 'output_tokens': 40})
        self.assertEqual((await self.assess(peers)).duplicates, result.duplicates)
        self.assertEqual(self.client.post.await_count, 2)

    async def test_approval_gate_does_not_turn_supported_dimensions_into_automatic_approval(self):
        payload = response()
        payload['answers']['automatic_approval'].update(choice='unsupported',
            probabilities={'supported': 0.1, 'unsupported': 0.9})
        self.client.post.return_value = httpx.Response(200, json=payload)
        result = await self.assess()
        self.assertEqual(result.outcome, 'ready')
        self.assertFalse(result.auto_approval_supported)

    async def test_manual_shipment_inspection_does_not_require_manual_definition_review(self):
        self.rule['spec'] = mapped(title='Wrap pallets', instruction='Wrap pallets securely.',
            subject='pallet', rule_type={'id': 'pallet.wrapping', 'version': 1},
            standard_check=None, verification='human', consumption_points=['pallet_building'],
            placements=[{'workflow': 'pallet_building', 'area': 'wrapping', 'behavior': 'display'}],
            evidence=[{'page': 1, 'quote': 'Wrap pallets securely.'}]).model_dump(mode='json')
        self.pages = {1: 'Wrap pallets securely.'}
        result = await self.assess()
        self.assertEqual(result.outcome, 'ready')
        self.assertEqual(self.rule['spec']['verification'], 'human')

    async def test_uncertainty_requires_review_but_supported_dimensions_do_not_invent_corrections(self):
        payload = response()
        payload['answers']['exceptions'].update(choice='uncertain',
            probabilities={'supported': 0.01, 'correction': 0.01, 'uncertain': 0.98})
        payload['answers']['classification']['confidence'] = 0.5
        self.client.post.return_value = httpx.Response(200, json=payload)
        result = await self.assess()
        self.assertEqual(result.outcome, 'needs_review')
        self.assertEqual({i.code for i in result.issues}, {'exceptions'})
        self.assertTrue(all(i.action and i.section for i in result.issues))

    async def test_correction_requires_a_specific_verified_proposal(self):
        payload = response()
        payload['answers']['exceptions'].update(choice='correction',
            probabilities={'supported': 0.3, 'correction': 0.4, 'uncertain': 0.3})
        self.client.post.return_value = httpx.Response(200, json=payload)
        result = await self.assess()
        self.assertEqual(result.outcome, 'needs_review')
        self.assertTrue(all(i.kind == 'manual' for i in result.issues))

    async def test_reference_requirement_is_ready_with_execution_gap_separate(self):
        from test_rules import rule
        self.rule['spec'] = rule(schema_version='1.2', assertion=None, verification='unresolved',
                                 execution_mode='reference_only').model_dump(mode='json')
        result = await self.assess()
        self.assertEqual(result.outcome, 'ready')
        self.assertTrue(result.execution_gaps)
        self.assertEqual(self.rule['status'], 'pending')

    async def test_visual_and_missing_text_are_never_ready(self):
        self.rule['spec']['evidence'][0]['kind'] = 'visual'
        self.pages = {1: None}
        result = await self.assess()
        self.assertEqual(result.outcome, 'needs_review')
        self.assertIsNone(result.confidence)
        self.assertFalse(result.dimensions)
        self.client.post.assert_not_awaited()

    async def test_context_limit_does_not_silently_truncate_or_call_provider(self):
        with patch.object(provider, 'MAX_CONTEXT_CHARACTERS', 1):
            result = await self.assess()
        self.assertEqual(result.outcome, 'needs_review')
        self.assertIn('context_limit', [i.code for i in result.issues])
        self.client.post.assert_not_awaited()

    async def test_invalid_answers_are_retained_and_not_repaid_on_resume(self):
        payload = response()
        del payload['answers']['exceptions']
        self.client.post.return_value = httpx.Response(200, json=payload)
        for _ in range(2):
            with self.assertRaises(provider.AssessmentResponseError):
                await self.assess()
        self.client.post.assert_awaited_once()
        self.assertEqual(json.loads(self.path.read_text())['raw'], payload)

    async def test_non_json_response_is_retained_and_can_be_skipped_without_another_call(self):
        self.client.post.return_value = httpx.Response(200, text='unusable answer')
        for _ in range(2):
            with self.assertRaises(provider.AssessmentResponseError):
                await self.assess()
        self.client.post.assert_awaited_once()
        self.assertEqual(json.loads(self.path.read_text())['invalid_response_text'], 'unusable answer')

    def test_failed_check_keeps_local_issues_but_never_claims_readiness(self):
        self.rule['spec']['unresolved_questions'] = ['Confirm the destination.']
        result = provider.failed_assessment(self.rule, [candidate()], self.pages, 'jev-test', 'failed-job')
        self.assertEqual(result.outcome, 'needs_review')
        self.assertTrue(result.check_failed)
        self.assertIsNone(result.confidence)
        self.assertFalse(result.dimensions)
        self.assertEqual({issue.code for issue in result.issues},
                         {'assessment_failed', 'unresolved_question', 'duplicates_unassessed'})

    def test_invalid_and_inconsistent_probabilities_fail_closed(self):
        for changes in ({'confidence': float('nan')}, {'confidence': True},
                        {'choice': 'correction'}, {'choice': []}, {'probabilities': {'supported': 1}}):
            payload = response()
            payload['answers']['classification'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ProviderFailure):
                provider.parse_dimensions(payload)

    async def test_provider_access_error_is_safe(self):
        self.client.post.return_value = httpx.Response(403, text='private-test-key source text')
        with self.assertRaises(ProviderFailure) as error:
            await self.assess()
        self.assertNotIsInstance(error.exception, provider.AssessmentResponseError)
        self.assertNotIn('private-test-key', str(error.exception))
        self.assertFalse(self.path.exists())

    async def test_stale_results_after_edits_decisions_or_duplicate_changes(self):
        result = await self.assess()
        self.rule['assessment'] = result.model_dump(mode='json')
        self.assertFalse(RunPayload(rules=[self.rule]).rules[0].assessment_stale)
        for change in ({'revision': 2}, {'status': 'approved'}):
            changed = {**self.rule, **change}
            self.assertTrue(RunPayload(rules=[changed]).rules[0].assessment_stale)
        peer = candidate(spec=deepcopy(self.rule['spec']))
        self.assertTrue(RunPayload(rules=[self.rule, peer]).rules[0].assessment_stale)
        changed = deepcopy(self.rule)
        changed['spec']['instruction'] += ' Edited.'
        self.assertTrue(RunPayload(rules=[changed]).rules[0].assessment_stale)
        self.assertEqual(self.rule['status'], 'pending')

    def test_preview_selection_and_resume_never_select_decided_or_foreign_rules(self):
        approved = candidate(status='approved')
        data = {'rules': [self.rule, approved]}
        body = StartAssessment(version=1, actor='Reviewer', scope='all')
        job = prepare_job(data, body, 'jev-test')
        self.assertEqual(job['pending'], [{'id': self.rule['id'], 'revision': 1}])
        self.assertTrue(job['auto_process'])
        with self.assertRaises(HTTPException):
            prepare_job(data, StartAssessment(version=1, actor='Reviewer', scope='selected', rule_ids=[uuid4()]), 'jev-test')
        data['assessment_job'] = {**job, 'status': 'failed'}
        resumed = prepare_job(data, StartAssessment(version=1, actor='Reviewer', resume=True), 'jev-test')
        self.assertEqual(resumed['id'], job['id'])
        with self.assertRaises(HTTPException):
            prepare_job(data, StartAssessment(version=1, actor='Reviewer', resume=True), 'other-model')
        data['classification_job'] = {'status': 'running'}
        with self.assertRaises(HTTPException):
            prepare_job(data, body, 'jev-test')

    def test_check_only_mode_is_preserved_on_resume(self):
        data = {'rules': [self.rule]}
        job = prepare_job(data, StartAssessment(version=1, actor='Reviewer', scope='all', auto_process=False), 'jev-test')
        self.assertFalse(job['auto_process'])
        data['assessment_job'] = {**job, 'status': 'failed'}
        resumed = prepare_job(data, StartAssessment(version=1, actor='Reviewer', resume=True, auto_process=True), 'jev-test')
        self.assertFalse(resumed['auto_process'])

    def test_cancelled_run_can_resume_without_resetting_work_or_enabling_automation(self):
        from routing_guides.resolution import RESOLUTION_VERSION
        data={'rules':[self.rule]}
        job=prepare_job(data,StartAssessment(version=1,actor='Reviewer',scope='all',auto_process=False),'jev-test')
        job.update(status='cancelled',processed=1,prepared=4,resolution_version=RESOLUTION_VERSION)
        data['assessment_job']=job
        resumed=prepare_job(data,StartAssessment(version=1,actor='Reviewer',resume=True),'jev-test')
        self.assertEqual(resumed['id'],job['id'])
        self.assertEqual(resumed['prepared'],4)
        self.assertFalse(resumed['auto_process'])
        job['resolution_version']='rule-resolution-1.1'
        with self.assertRaises(HTTPException):
            prepare_job(data,StartAssessment(version=1,actor='Reviewer',resume=True),'jev-test')

    def test_failed_retry_selects_only_pending_failed_checks_with_new_response_storage(self):
        failed = candidate(assessment={'check_failed': True})
        approved = candidate(status='approved', assessment={'check_failed': True})
        old = {'id': 'previous-job', 'status': 'complete', 'pending': []}
        data = {'rules': [self.rule, failed, approved], 'assessment_job': old}
        before = deepcopy(data)
        body = StartAssessment(version=1, actor='Reviewer', scope='failed')
        job = prepare_job(data, body, 'jev-test')
        self.assertEqual(job['pending'], [{'id': failed['id'], 'revision': failed['revision']}])
        self.assertNotEqual(job['id'], old['id'])
        self.assertEqual(data, before)
        data['assessment_job'].update(status='failed', pending=[{'id': self.rule['id'], 'revision': 1}])
        with self.assertRaises(HTTPException):
            prepare_job(data, body, 'jev-test')
        data['assessment_job']['status'] = 'cancelled'
        self.assertEqual(prepare_job(data, body, 'jev-test')['total'], 1)
        data['rules'] = [self.rule, approved]
        with self.assertRaises(HTTPException):
            prepare_job(data, body, 'jev-test')

    def test_resume_keeps_gateway_connection_and_rejects_model_changes(self):
        data = {'rules': [self.rule]}
        job = prepare_job(data, StartAssessment(version=1, actor='Reviewer', scope='all'), 'jev-test')
        job.update(status='cancelled', resolution_provider='litellm', resolution_model='argon-team-alias')
        data['assessment_job'] = job
        resumed = prepare_job(data, StartAssessment(version=1, actor='Reviewer', resume=True), 'jev-test')
        self.assertEqual(resumed['resolution_provider'], 'litellm')
        self.assertEqual(resumed['resolution_model'], 'argon-team-alias')
        for changes in [{'preparation_provider': 'anthropic'}, {'preparation_model': 'different-alias'}]:
            with self.subTest(changes=changes), self.assertRaises(HTTPException) as caught:
                prepare_job(data, StartAssessment(version=1, actor='Reviewer', resume=True, **changes), 'jev-test')
            self.assertEqual(caught.exception.status_code, 409)

    def test_all_selection_is_not_limited_to_sample_size_or_visible_selection(self):
        rules = [candidate() for _ in range(40)]
        data = {'rules': [*rules, candidate(status='approved'), candidate(status='ignored')]}
        job = prepare_job(data, StartAssessment(version=1, actor='Reviewer', scope='all',
                                               rule_ids=[rules[0]['id']], sample_size=25), 'jev-test')
        self.assertEqual(job['total'], 40)
        self.assertEqual({r['id'] for r in job['pending']}, {r['id'] for r in rules})

    def test_sample_includes_different_review_needs_without_selecting_approved_rules(self):
        rules = [candidate() for _ in range(30)]
        flagged = candidate()
        flagged['spec']['unresolved_questions'] = ['Confirm destination scope.']
        rules += [flagged, candidate(status='approved')]
        selected = choose_sample(rules, 3)
        self.assertEqual(len(selected), 3)
        self.assertIn(flagged['id'], [r['id'] for r in selected])
        self.assertTrue(all(r['status'] == 'pending' for r in selected))
