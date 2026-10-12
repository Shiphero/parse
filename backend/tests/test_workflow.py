"""Integration checks use a rollback-only transaction, never the user's guide records."""
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from routing_guides.config import get_settings
from routing_guides.models import Retailer, ReleaseHead, Guide, GuidePage, AnalysisRun, RuleRelease
from routing_guides.rules import Extraction
from routing_guides.analysis_provider import ProviderOutput, ProviderFailure
from routing_guides import workflow_api, analysis_jobs
from test_rules import rule


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(get_settings().database_url.get_secret_value())
        self.conn = await self.engine.connect()
        self.transaction = await self.conn.begin()
        self.sessions = async_sessionmaker(self.conn,expire_on_commit=False,join_transaction_mode='create_savepoint')
        self.patches = [patch.object(workflow_api,'sessions',self.sessions),patch.object(analysis_jobs,'sessions',self.sessions)]
        for p in self.patches:p.start()
        self.retailer='test-'+uuid4().hex
        self.gid=uuid4(); self.rid=uuid4()
        self.temp=TemporaryDirectory()
        self.app=FastAPI();self.app.include_router(workflow_api.router)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test')
        async with self.sessions.begin() as s:
            s.add(Retailer(id=self.retailer,name='Synthetic test',discovery_note='Rollback-only fixture'))
            await s.flush()
            s.add(ReleaseHead(retailer_id=self.retailer,release_id=None))
            s.add(Guide(id=self.gid,retailer_id=self.retailer,title='Synthetic',filename='synthetic.pdf',sha256=uuid4().hex,size_bytes=1,status='ready',page_count=1,processed_pages=1,attention_pages=0))
            await s.flush()
            s.add(GuidePage(guide_id=self.gid,page_index=0,text='Cartons must not exceed 50 lb.',text_status='extracted',image_status='ready'))
            s.add(AnalysisRun(id=self.rid,guide_id=self.gid,status='complete',version=1,config={'provider':'manual'},payload={'rules':[], 'coverage':[{'page':1,'outcome':'rules_found','note':'Test fixture'}], 'warnings':[], 'batches':[], 'pending_batches':[]}))

    async def asyncTearDown(self):
        await self.client.aclose()
        for p in reversed(self.patches):p.stop()
        await self.transaction.rollback();await self.conn.close();await self.engine.dispose();self.temp.cleanup()

    async def send(self,method,path,body,status=200):
        response=await self.client.request(method,path,json=body)
        self.assertEqual(response.status_code,status,response.text)
        return response.json()

    async def test_review_publish_evaluate_and_immutable_revision(self):
        actor='Test reviewer'
        run=await self.send('POST',f'/api/analysis/{self.rid}/rules',{'version':1,'actor':actor,'spec':rule().model_dump(mode='json')})
        candidate=run['payload']['rules'][0]
        endpoint=f'/api/analysis/{self.rid}/rules/{candidate["id"]}'
        await self.send('PUT',endpoint,{'version':1,'actor':actor,'action':'approve','note':'Stale'},409)
        run=await self.send('PUT',endpoint,{'version':run['version'],'actor':actor,'action':'approve','note':'Verified source'})
        self.assertEqual(run['payload']['rules'][0]['status'],'approved')
        run=await self.send('PUT',endpoint,{'version':run['version'],'actor':actor,'action':'save','note':'Corrected interpretation','spec':rule().model_dump(mode='json')})
        self.assertEqual(run['payload']['rules'][0]['status'],'pending')
        self.assertIsNone(run['payload']['rules'][0]['review'])
        publish={'version':run['version'],'actor':actor,'note':'Test coverage verified','name':'Test release','effective_date':'2026-01-01','scope':'Synthetic carton test only','coverage_confirmed':True,'impact_confirmed':True,'decisions':{},'base_release_id':None}
        await self.send('POST',f'/api/analysis/{self.rid}/publish',publish,409)
        run=await self.send('PUT',endpoint,{'version':run['version'],'actor':actor,'action':'approve','note':'Verified changed revision'})
        publish['version']=run['version']
        release=await self.send('POST',f'/api/analysis/{self.rid}/publish',publish)
        repeat=await self.send('POST',f'/api/analysis/{self.rid}/publish',publish)
        self.assertEqual(repeat['id'],release['id'])
        await self.send('PUT',endpoint,{'version':run['version'],'actor':actor,'action':'save','note':'Corrected interpretation','spec':rule().model_dump(mode='json')},409)
        for weight,outcome in [('50','pass'),('51','fail'),(None,'cannot_determine')]:
            raw={'schema_version':'1.0','shipment':{},'cartons':[{} if weight is None else {'weight':{'value':weight,'unit':'lb'}}]}
            scenario=await self.send('POST','/api/scenarios',{'retailer_id':self.retailer,'name':'Synthetic scenario','raw':raw})
            result=await self.send('POST',f'/api/scenarios/{scenario["id"]}/evaluate/{release["id"]}',{})
            self.assertEqual(result['items'][0]['outcome'],outcome)
            self.assertEqual(result['release_id'],release['id'])
        history=await self.client.get(f'/api/audit/{self.rid}')
        self.assertGreaterEqual(len(history.json()),4)

    async def test_analysis_resume_saves_each_batch_and_does_not_duplicate(self):
        async with self.sessions.begin() as s:
            run=await s.get(AnalysisRun,self.rid)
            run.status='queued';run.config={'provider':'anthropic','model':'test-model'}
            run.payload={**run.payload,'coverage':[],'pending_batches':[[1]]}
        output=ProviderOutput(Extraction(rules=[rule()],coverage=[{'page':1,'outcome':'rules_found','note':'Text rule'}],warnings=[]),'returned-model',{'input_tokens':100})
        with patch.object(analysis_jobs,'analyze',AsyncMock(side_effect=ProviderFailure('Provider unavailable'))):
            await analysis_jobs.run_analysis(self.rid)
        async with self.sessions() as s:
            run=await s.get(AnalysisRun,self.rid)
            self.assertEqual(run.status,'failed');self.assertEqual(run.payload['pending_batches'],[[1]])
        mocked=AsyncMock(return_value=output)
        with patch.object(analysis_jobs,'analyze',mocked):
            await analysis_jobs.run_analysis(self.rid)
            await analysis_jobs.run_analysis(self.rid)
        self.assertEqual(mocked.await_count,1)
        async with self.sessions() as s:
            run=await s.get(AnalysisRun,self.rid)
            self.assertEqual(run.status,'complete');self.assertEqual(len(run.payload['rules']),1)
            self.assertEqual(run.payload['batches'][0]['model'],'returned-model')

    async def test_updated_release_preserves_identity_and_exposes_scenario_impact(self):
        actor = 'Test reviewer'
        async def approve(run_id, spec):
            run = await self.send('POST', f'/api/analysis/{run_id}/rules', {'version': 1, 'actor': actor, 'spec': spec})
            candidate = run['payload']['rules'][0]['id']
            run = await self.send('PUT', f'/api/analysis/{run_id}/rules/{candidate}', {'version': run['version'], 'actor': actor, 'action': 'approve', 'note': 'Synthetic source verified'})
            return run, candidate

        run, candidate = await approve(self.rid, rule().model_dump(mode='json'))
        publish = {'version': run['version'], 'actor': actor, 'note': 'Synthetic coverage verified', 'name': 'Original', 'effective_date': '2026-01-01', 'scope': 'Synthetic carton fixture', 'coverage_confirmed': True, 'impact_confirmed': True, 'decisions': {}, 'base_release_id': None}
        original = await self.send('POST', f'/api/analysis/{self.rid}/publish', publish)
        stable_id = original['payload']['rules'][0]['stable_id']
        self.assertEqual(stable_id, candidate)
        scenario = await self.send('POST', '/api/scenarios', {'retailer_id': self.retailer, 'name': '45 lb carton', 'raw': {'schema_version': '1.0', 'shipment': {}, 'cartons': [{'weight': {'value': 45, 'unit': 'lb'}}]}})
        updated_id = uuid4()
        async with self.sessions.begin() as session:
            # Same source permits a stricter synthetic proposal; this checks release mechanics, not extraction quality.
            session.add(AnalysisRun(id=updated_id, guide_id=self.gid, status='complete', version=1, config={'provider': 'manual'}, payload={'rules': [], 'coverage': [{'page': 1, 'outcome': 'rules_found', 'note': 'Synthetic fixture'}], 'warnings': [], 'batches': [], 'pending_batches': []}))
        spec = rule().model_dump(mode='json')
        spec['assertion']['value'] = 40
        run, replacement = await approve(updated_id, spec)
        update = {**publish, 'version': run['version'], 'name': 'Updated', 'base_release_id': original['id']}
        await self.send('POST', f'/api/analysis/{updated_id}/publish', update, 422)
        update['decisions'] = {stable_id: 'replace:' + replacement}
        impact = await self.send('POST', f'/api/analysis/{updated_id}/impact', update)
        item = next(s for s in impact['scenarios'] if s['id'] == scenario['id'])
        self.assertEqual(item['before']['items'][0]['outcome'], 'pass')
        self.assertEqual(item['after']['items'][0]['outcome'], 'fail')
        updated = await self.send('POST', f'/api/analysis/{updated_id}/publish', update)
        self.assertEqual(updated['payload']['rules'][0]['stable_id'], stable_id)
        await self.send('POST', f'/api/releases/{original["id"]}/activate', {'actor': actor, 'note': 'Restore fixture', 'expected_active_id': original['id']}, 409)
        await self.send('POST', f'/api/releases/{original["id"]}/activate', {'actor': actor, 'note': 'Restore fixture', 'expected_active_id': updated['id']})
        old_result = await self.send('POST', f'/api/scenarios/{scenario["id"]}/evaluate/{original["id"]}', {})
        self.assertEqual(old_result['items'][0]['outcome'], 'pass')

    async def test_missing_coverage_is_not_completed(self):
        async with self.sessions.begin() as s:
            run=await s.get(AnalysisRun,self.rid);run.status='queued';run.config={'provider':'anthropic','model':'test'}
            run.payload={**run.payload,'coverage':[],'pending_batches':[[1]]}
        with patch.object(analysis_jobs,'analyze',AsyncMock(return_value=ProviderOutput(Extraction(rules=[],coverage=[],warnings=[]),'test',{}))):
            await analysis_jobs.run_analysis(self.rid)
        async with self.sessions() as s:
            run=await s.get(AnalysisRun,self.rid)
            self.assertEqual(run.status,'failed');self.assertEqual(run.payload['coverage'],[])

    async def test_citation_issues_preserve_drafts_and_continue_but_block_approval(self):
        bad = rule(evidence=[{'page': 1, 'quote': 'Cartons may weigh up to 60 lb.'}])
        good = rule(evidence=[{'page': 2, 'quote': '50 lb'}])
        async with self.sessions.begin() as session:
            guide = await session.get(Guide, self.gid)
            guide.page_count = 2
            session.add(GuidePage(guide_id=self.gid, page_index=1, text='Maximum weight is 50 lb.', text_status='extracted', image_status='ready'))
            run = await session.get(AnalysisRun, self.rid)
            run.status = 'queued'
            run.config = {'provider': 'anthropic', 'model': 'test'}
            run.payload = {**run.payload, 'coverage': [], 'pending_batches': [[1], [2]]}
        responses = [
            ProviderOutput(Extraction(rules=[bad, bad], coverage=[{'page': 1, 'outcome': 'rules_found', 'note': 'Proposed requirements'}], warnings=[]), 'test', {}),
            ProviderOutput(Extraction(rules=[good], coverage=[{'page': 2, 'outcome': 'rules_found', 'note': 'Matched'}], warnings=[]), 'test', {}),
        ]
        with patch.object(analysis_jobs, 'analyze', AsyncMock(side_effect=responses)) as provider:
            await analysis_jobs.run_analysis(self.rid)
            await analysis_jobs.run_analysis(self.rid)
        self.assertEqual(provider.await_count, 2)
        async with self.sessions() as session:
            saved = await session.get(AnalysisRun, self.rid)
            self.assertEqual(saved.status, 'complete')
            self.assertEqual(len(saved.payload['rules']), 3)
            self.assertEqual(saved.payload['coverage'][0]['outcome'], 'needs_review')
            self.assertEqual(saved.payload['coverage'][1]['outcome'], 'rules_found')
            self.assertEqual(saved.payload['rules'][0]['spec']['evidence'][0]['quote'], bad.evidence[0].quote)
            self.assertTrue(saved.payload['rules'][0]['evidence_issues'])
            self.assertFalse(saved.payload['rules'][2]['evidence_issues'])
            version = saved.version
            first, second = [r['id'] for r in saved.payload['rules'][:2]]
        endpoint = f'/api/analysis/{self.rid}/rules/{first}'
        body = {'version': version, 'actor': 'Reviewer', 'note': 'Checked source'}
        await self.send('PUT', endpoint, {**body, 'action': 'approve'}, 422)
        rejected = await self.send('PUT', endpoint, {**body, 'action': 'reject'})
        self.assertEqual(rejected['payload']['rules'][0]['status'], 'rejected')
        endpoint = f'/api/analysis/{self.rid}/rules/{second}'
        body['version'] = rejected['version']
        await self.send('PUT', endpoint, {**body, 'action': 'save', 'spec': bad.model_dump(mode='json')}, 422)
        edited = await self.send('PUT', endpoint, {**body, 'action': 'save', 'spec': rule().model_dump(mode='json')})
        self.assertEqual(edited['payload']['rules'][1]['evidence_issues'], [])
        approved = await self.send('PUT', endpoint, {**body, 'version': edited['version'], 'action': 'approve'})
        self.assertEqual(approved['payload']['rules'][1]['status'], 'approved')
        self.assertEqual(approved['payload']['coverage'][0]['outcome'], 'needs_review')

    async def add_candidate(self, version, spec=None, run_id=None):
        return await self.send('POST', f'/api/analysis/{run_id or self.rid}/rules',
                               {'version': version, 'actor': 'Reviewer', 'spec': (spec or rule()).model_dump(mode='json')})

    async def test_bulk_approval_is_atomic_and_audits_each_revision(self):
        run = await self.add_candidate(1)
        run = await self.add_candidate(run['version'], rule(title='Another rule'))
        rules = run['payload']['rules']
        body = {'version': run['version'], 'actor': 'Reviewer', 'revisions': {r['id']: r['revision'] for r in rules}}
        url = f'/api/analysis/{self.rid}/bulk-approve'
        await self.send('POST', url, {**body, 'actor': '   '}, 422)
        await self.send('POST', url, {**body, 'revisions': {}}, 422)
        await self.send('POST', url, {**body, 'version': 1}, 409)
        # A rule selector from outside this draft cannot sneak into a batch.
        await self.send('POST', url, {**body, 'revisions': {rules[0]['id']: 1, str(uuid4()): 1}}, 404)
        await self.send('POST', url, {**body, 'revisions': {rules[0]['id']: 1, rules[1]['id']: 2}}, 409)
        async with self.sessions() as session:
            saved = await session.get(AnalysisRun, self.rid)
            self.assertEqual(saved.version, run['version'])
            self.assertTrue(all(r['status'] == 'pending' for r in saved.payload['rules']))
        result = await self.send('POST', url, body)
        self.assertEqual(result['version'], body['version'] + 1)
        for candidate in result['payload']['rules']:
            self.assertEqual(candidate['status'], 'approved')
            self.assertEqual(candidate['review']['revision'], candidate['revision'])
            self.assertEqual(candidate['review']['note'], '')
            self.assertEqual(candidate['review']['mode'], 'bulk')
        audits = (await self.client.get(f'/api/audit/{self.rid}')).json()
        approvals = [a for a in audits if a['action'] == 'approve']
        self.assertEqual(len(approvals), 2)
        self.assertEqual(approvals[0]['payload']['batch_id'], approvals[1]['payload']['batch_id'])
        await self.send('POST', url, {**body, 'version': result['version']}, 409)

    async def test_flagged_batch_rejected_and_single_approval_notes_are_conditional(self):
        run = await self.add_candidate(1)
        good = run['payload']['rules'][0]['id']
        run = await self.add_candidate(run['version'], rule(title='Unresolved rule', unresolved_questions=['Check applicability']))
        flagged = run['payload']['rules'][1]['id']
        self.assertTrue(run['payload']['rules'][1]['individual_review_reasons'])
        body = {'version': run['version'], 'actor': 'Reviewer'}
        await self.send('POST', f'/api/analysis/{self.rid}/bulk-approve',
                        {**body, 'revisions': {good: 1, flagged: 1}}, 422)
        endpoint = f'/api/analysis/{self.rid}/rules/{good}'
        await self.send('PUT', endpoint, {**body, 'action': 'reject'}, 422)
        await self.send('PUT', endpoint, {**body, 'action': 'save', 'spec': rule().model_dump(mode='json')}, 422)
        run = await self.send('PUT', endpoint, {**body, 'action': 'approve'})
        self.assertEqual(run['payload']['rules'][0]['review']['note'], '')
        self.assertEqual(run['payload']['rules'][1]['status'], 'pending')
        body['version'] = run['version']
        endpoint = f'/api/analysis/{self.rid}/rules/{flagged}'
        await self.send('PUT', endpoint, {**body, 'action': 'approve'}, 422)
        run = await self.send('PUT', endpoint, {**body, 'action': 'approve', 'note': 'Retained as unresolved; needs operational evidence'})
        self.assertEqual(run['payload']['rules'][1]['status'], 'approved')

    async def test_foreign_retailer_release_and_foreign_draft_rule_are_rejected(self):
        run = await self.add_candidate(1)
        foreign_retailer = 'foreign-' + uuid4().hex
        foreign_guide, foreign_run, foreign_release, foreign_rule = [uuid4() for _ in range(4)]
        async with self.sessions.begin() as session:
            session.add(Retailer(id=foreign_retailer, name='Other retailer', discovery_note='Fixture'))
            await session.flush()
            session.add(Guide(id=foreign_guide, retailer_id=foreign_retailer, title='Foreign guide', filename='foreign.pdf',
                sha256=uuid4().hex, size_bytes=1, status='ready', page_count=1, processed_pages=1, attention_pages=0))
            await session.flush()
            payload = deepcopy(run['payload'])
            payload['rules'][0]['id'] = str(foreign_rule)
            payload['rules'][0]['source_guide_id'] = str(foreign_guide)
            session.add(AnalysisRun(id=foreign_run, guide_id=foreign_guide, status='complete', version=1,
                config={'provider': 'manual'}, payload=payload))
            await session.flush()
            session.add(RuleRelease(id=foreign_release, retailer_id=foreign_retailer, run_id=foreign_run,
                name='Foreign release', effective_date=workflow_api.date(2026, 1, 1), payload={'rules': [], 'scope': 'Foreign'}))
        await self.send('POST', f'/api/analysis/{self.rid}/carry-approvals',
            {'version': run['version'], 'actor': 'Reviewer', 'scope_confirmed': True, 'base_release_id': str(foreign_release)}, 409)
        await self.send('POST', f'/api/analysis/{self.rid}/bulk-approve',
            {'version': run['version'], 'actor': 'Reviewer', 'revisions': {str(foreign_rule): 1}}, 404)
        async with self.sessions() as session:
            for rid, version in [(self.rid, run['version']), (foreign_run, 1)]:
                saved = await session.get(AnalysisRun, rid)
                self.assertEqual(saved.version, version)
                self.assertEqual(saved.payload['rules'][0]['status'], 'pending')

    async def test_bulk_revalidates_source_even_without_stored_flags(self):
        run = await self.add_candidate(1)
        candidate = run['payload']['rules'][0]
        async with self.sessions.begin() as session:
            saved = await session.get(AnalysisRun, self.rid)
            data = deepcopy(saved.payload)
            data['rules'][0]['spec']['evidence'][0]['quote'] = 'Not in the source'
            saved.payload = data
        await self.send('POST', f'/api/analysis/{self.rid}/bulk-approve',
                        {'version': run['version'], 'actor': 'Reviewer', 'revisions': {candidate['id']: 1}}, 422)

    async def test_carry_forward_approval_identity_scope_and_edit_invalidation(self):
        run = await self.add_candidate(1)
        candidate = run['payload']['rules'][0]['id']
        run = await self.send('PUT', f'/api/analysis/{self.rid}/rules/{candidate}',
                              {'version': run['version'], 'actor': 'Original reviewer', 'action': 'approve'})
        publish = {'version': run['version'], 'actor': 'Publisher', 'note': 'Fixture coverage verified',
                   'name': 'Original', 'effective_date': '2026-01-01', 'scope': 'Cartons',
                   'coverage_confirmed': True, 'impact_confirmed': True, 'decisions': {}, 'base_release_id': None}
        original = await self.send('POST', f'/api/analysis/{self.rid}/publish', publish)
        updated_id = uuid4()
        async with self.sessions.begin() as session:
            session.add(AnalysisRun(id=updated_id, guide_id=self.gid, status='complete', version=1,
                        config={'provider': 'manual'}, payload={'rules': [], 'coverage': run['payload']['coverage'],
                        'warnings': [], 'batches': [], 'pending_batches': []}))
        updated = await self.add_candidate(1, run_id=updated_id)
        replacement = updated['payload']['rules'][0]['id']
        comparison = (await self.client.get(f'/api/analysis/{updated_id}/comparison')).json()
        self.assertEqual(comparison['unchanged'], {replacement: candidate})
        body = {'version': updated['version'], 'actor': 'Update reviewer', 'base_release_id': original['id'], 'scope_confirmed': True}
        url = f'/api/analysis/{updated_id}/carry-approvals'
        await self.send('POST', url, {**body, 'scope_confirmed': False}, 422)
        await self.send('POST', url, {**body, 'base_release_id': str(uuid4())}, 409)
        updated = await self.send('POST', url, body)
        carried = updated['payload']['rules'][0]
        self.assertEqual(carried['review']['prior_review']['actor'], 'Original reviewer')
        self.assertEqual(carried['carried_from_rule_id'], candidate)
        self.assertEqual(carried['review']['revision'], 1)
        # Editing invalidates both approval and the inherited stable-ID mapping.
        updated = await self.send('PUT', f'/api/analysis/{updated_id}/rules/{replacement}',
            {'version': updated['version'], 'actor': 'Editor', 'action': 'save', 'note': 'Checked the interpretation', 'spec': rule().model_dump(mode='json')})
        self.assertIsNone(updated['payload']['rules'][0]['carried_from_rule_id'])
        self.assertIsNone(updated['payload']['rules'][0]['review'])
        updated = await self.send('POST', url, {**body, 'version': updated['version']})
        update = {**publish, 'version': updated['version'], 'name': 'Updated', 'base_release_id': original['id']}
        await self.send('POST', f'/api/analysis/{updated_id}/publish', {**update, 'decisions': {candidate: 'retain'}}, 422)
        result = await self.send('POST', f'/api/analysis/{updated_id}/publish', update)
        self.assertEqual(len(result['payload']['rules']), 1)
        self.assertEqual(result['payload']['rules'][0]['stable_id'], candidate)
        self.assertEqual(result['payload']['rules'][0]['draft_id'], replacement)
        self.assertEqual(result['payload']['decisions'], {candidate: 'replace:' + replacement})

    async def test_credentials_are_masked_and_cross_origin_write_rejected(self):
        with patch('routing_guides.connections.get_settings',return_value=SimpleNamespace(storage_root=Path(self.temp.name),anthropic_api_key=SimpleNamespace(get_secret_value=lambda:''),anthropic_model='',openai_api_key=SimpleNamespace(get_secret_value=lambda:''),openai_model='')):
            response=await self.client.put('/api/connections/anthropic',json={'key':'synthetic-test-secret','model':'test'})
            self.assertEqual(response.status_code,403)
            with patch.object(workflow_api.psycopg.AsyncConnection,'connect',new=AsyncMock()) as connect:
                manager=AsyncMock()
                manager.__aenter__.return_value=manager
                connect.return_value=manager
                response=await self.client.put('/api/connections/anthropic',headers={'X-Requested-With':'routing-guide-parser'},json={'key':'synthetic-test-secret','model':'test'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertNotIn('synthetic-test-secret',response.text)
            path=Path(self.temp.name)/'connections.json'
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertIn('synthetic-test-secret',path.read_text())
