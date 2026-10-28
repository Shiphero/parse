"""Concurrency and cache validity checks; never call external providers."""
import asyncio
from copy import deepcopy
import unittest

from routing_guides.review_processing import completed_batch, preparation_fingerprint, reusable_preparation
from routing_guides.resolution import RESOLUTION_VERSION
from test_assessment import candidate


class ProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def test_next_rule_starts_while_a_slow_peer_is_still_running(self):
        fifth_started = asyncio.Event()
        active = peak = 0
        async def work(number):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            try:
                if number == 0:
                    await asyncio.wait_for(fifth_started.wait(), 2)
                if number == 4:
                    fifth_started.set()
                await asyncio.sleep(0)
                return number
            finally:
                active -= 1
        outputs = []
        async with completed_batch(range(8), work) as results:
            async for item, value, error in results:
                self.assertIsNone(error)
                outputs.append(value)
        self.assertEqual(sorted(outputs), list(range(8)))
        self.assertLessEqual(peak, 4)
        self.assertTrue(fifth_started.is_set())

    async def test_fatal_failure_stops_refill_but_preserves_running_results(self):
        failed = False
        started = set()
        gate = asyncio.Event()
        async def work(number):
            started.add(number)
            if len(started) == 4:
                gate.set()
            await gate.wait()
            if number == 0:
                raise ValueError('Cannot continue')
            await asyncio.sleep(.01)
            return number
        saved = []
        async with completed_batch(range(20), work, keep_running=lambda: not failed) as results:
            async for item, value, error in results:
                if error:
                    failed = True
                else:
                    saved.append(value)
        self.assertEqual(started, {0, 1, 2, 3})
        self.assertEqual(sorted(saved), [1, 2, 3])

    async def test_completions_do_not_wait_for_slowest_rule_and_close_cancels_inflight_work(self):
        all_started = asyncio.Event()
        blocked = asyncio.Event()
        started, cancelled = set(), set()
        async def work(number):
            started.add(number)
            if len(started) == 4:
                all_started.set()
            await all_started.wait()
            if number == 2:
                return 'ready'
            try:
                await blocked.wait()
            except asyncio.CancelledError:
                cancelled.add(number)
                raise
        async with completed_batch(range(4), work) as results:
            number, value, error = await asyncio.wait_for(anext(results), 2)
            self.assertEqual((number, value, error), (2, 'ready', None))
        self.assertEqual(cancelled, {0, 1, 3})

    def test_preparation_reuse_requires_matching_revision_models_and_decision_state(self):
        rule = candidate()
        job = {'resolution_provider':'anthropic', 'resolution_model':'test', 'model':'jev', 'resolution_version':RESOLUTION_VERSION}
        rule['resolution'] = {'revision':1, 'provider':'anthropic', 'model':'test', 'verifier_model':'jev',
            'prompt_version':RESOLUTION_VERSION, 'failed':False, 'output_fingerprint':preparation_fingerprint(rule)}
        self.assertTrue(reusable_preparation(rule,job))
        for update in ({'revision':2}, {'status':'approved'}, {'review':{'actor':'Human'}},
                       {'spec':{**rule['spec'],'instruction':'Changed instruction'}}):
            self.assertFalse(reusable_preparation({**rule,**update},job))
        for update in ({'resolution_model':'different'}, {'model':'different'}):
            self.assertFalse(reusable_preparation(rule,{**job,**update}))
        failed=deepcopy(rule)
        failed['resolution']['failed']=True
        self.assertFalse(reusable_preparation(failed,job))

    def test_legacy_unchanged_preparation_is_reusable_but_unknown_verified_changes_are_not(self):
        rule = candidate()
        job = {'resolution_provider':'anthropic','resolution_model':'test','model':'jev','resolution_version':RESOLUTION_VERSION}
        rule['resolution']={'revision':1,'provider':'anthropic','model':'test','prompt_version':'rule-resolution-1.1','changes':[]}
        self.assertTrue(reusable_preparation(rule,job))
        rule['resolution']['changes']=[{'applied':True}]
        self.assertFalse(reusable_preparation(rule,job))

    def test_old_completed_work_is_reused_but_unapplied_bundles_are_reconsidered(self):
        rule = candidate()
        job = {'resolution_provider':'anthropic','resolution_model':'test','model':'jev','resolution_version':RESOLUTION_VERSION}
        rule['resolution'] = {'revision':1,'provider':'anthropic','model':'test','verifier_model':'jev',
            'prompt_version':'rule-resolution-1.2','output_fingerprint':preparation_fingerprint(rule),'changes':[]}
        self.assertTrue(reusable_preparation(rule, job))
        rule['resolution']['changes'] = [{'applied':True}]
        self.assertTrue(reusable_preparation(rule, job))
        rule['resolution']['changes'].append({'applied':False})
        self.assertFalse(reusable_preparation(rule, job))
