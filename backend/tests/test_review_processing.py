"""Concurrency and cache validity checks; never call external providers."""
import asyncio
from copy import deepcopy
import unittest

from routing_guides.review_processing import completed_batch, preparation_fingerprint, reusable_preparation
from routing_guides.resolution import RESOLUTION_VERSION
from test_assessment import candidate


class ProcessingTests(unittest.IsolatedAsyncioTestCase):
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
