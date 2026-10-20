"""Integration checks use a rollback-only transaction, never the user's guide records."""
import unittest
from copy import deepcopy
from datetime import date
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
from routing_guides import workflow_api, analysis_jobs, classification_jobs
from test_rules import rule


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(get_settings().database_url.get_secret_value())
        self.conn = await self.engine.connect()
        self.transaction = await self.conn.begin()
        self.sessions = async_sessionmaker(self.conn,expire_on_commit=False,join_transaction_mode='create_savepoint')
        self.patches = [patch.object(workflow_api,'sessions',self.sessions),patch.object(analysis_jobs,'sessions',self.sessions),patch.object(classification_jobs,'sessions',self.sessions)]
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

    async def published_fixture(self):
        run = await self.add_candidate(1)
        rid = run['payload']['rules'][0]['id']
        run = await self.send('PUT', f'/api/analysis/{self.rid}/rules/{rid}',
            {'version': run['version'], 'actor': 'Reviewer', 'action': 'approve'})
        body = dict(version=run['version'], actor='Publisher', note='Synthetic coverage',
                    name='Original', effective_date='2026-01-01', scope='Cartons',
                    coverage_confirmed=True, impact_confirmed=True, decisions={}, base_release_id=None)
        release = await self.send('POST', f'/api/analysis/{self.rid}/publish', body)
        return release, body

    async def test_version_delete_restore_preserves_payload_and_blocks_stale_writes(self):
        headers = {'X-Requested-With': 'routing-guide-parser'}
        url = f'/api/analysis/{self.rid}'
        body = {'version': 1, 'actor': 'Reviewer'}
        self.assertEqual((await self.client.post(url+'/delete', json=body)).status_code, 403)
        deleted = await self.client.post(url+'/delete', json=body, headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()['status'], 'deleted')
        workflow = (await self.client.get(f'/api/guides/{self.gid}/workflow')).json()
        self.assertEqual(workflow['runs'], [])
        self.assertEqual(len(workflow['deleted_runs']), 1)
        # A queued task must not resurrect a deleted analysis.
        await analysis_jobs.run_analysis(self.rid)
        self.assertEqual((await self.client.post(url+'/restore', json=body, headers=headers)).status_code, 409)
        restored = await self.client.post(url+'/restore', json={**body, 'version': 2}, headers=headers)
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()['status'], 'complete')
        self.assertEqual(restored.json()['payload'], deleted.json()['payload'])
        self.assertNotIn('deletion', restored.json()['config'])

    async def test_delete_active_release_requires_unpublish_and_restore_does_not_activate(self):
        release, _ = await self.published_fixture()
        headers = {'X-Requested-With': 'routing-guide-parser'}
        url = f'/api/analysis/{self.rid}'
        workflow_url = f'/api/guides/{self.gid}/workflow'
        workflow = (await self.client.get(workflow_url)).json()
        version = workflow['runs'][0]['version']
        body = {'version': version, 'actor': 'Reviewer'}
        self.assertEqual((await self.client.post(url+'/delete', json=body, headers=headers)).status_code, 409)
        await self.send('POST', f'/api/releases/{release["id"]}/unpublish',
                        {'actor': 'Reviewer', 'note': 'Retire fixture', 'expected_active_id': release['id']})
        deleted = await self.client.post(url+'/delete', json=body, headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual((await self.client.get(workflow_url)).json()['releases'], [])
        await self.send('POST', f'/api/releases/{release["id"]}/activate',
                        {'actor': 'Reviewer', 'note': 'Restore fixture', 'expected_active_id': None}, 409)
        self.assertEqual((await self.client.get(f'/api/releases/{release["id"]}/export?format=json')).status_code, 200)
        restored = await self.client.post(url+'/restore', json={**body, 'version': version+1}, headers=headers)
        self.assertEqual(restored.status_code, 200, restored.text)
        workflow = (await self.client.get(workflow_url)).json()
        self.assertEqual(workflow['runs'][0]['status'], 'published')
        self.assertEqual(len(workflow['releases']), 1)
        self.assertIsNone(workflow['active_release_id'])

    async def test_cannot_delete_analysis_or_classification_in_progress(self):
        headers = {'X-Requested-With': 'routing-guide-parser'}
        for status in ('queued', 'running'):
            async with self.sessions.begin() as session:
                run = await session.get(AnalysisRun, self.rid)
                run.status = status
            response = await self.client.post(f'/api/analysis/{self.rid}/delete',
                json={'version': 1, 'actor': 'Reviewer'}, headers=headers)
            self.assertEqual(response.status_code, 409)
        async with self.sessions.begin() as session:
            run = await session.get(AnalysisRun, self.rid)
            run.status = 'complete'
            run.payload = {**run.payload, 'classification_job': {'status': 'running'}}
        response = await self.client.post(f'/api/analysis/{self.rid}/delete',
            json={'version': 1, 'actor': 'Reviewer'}, headers=headers)
        self.assertEqual(response.status_code, 409)

    async def test_separate_guide_retains_other_rules_and_blocks_retirement(self):
        original, _ = await self.published_fixture()
        gid, rid = uuid4(), uuid4()
        async with self.sessions.begin() as session:
            session.add(Guide(id=gid, retailer_id=self.retailer, title='Transportation',
                filename='transport.pdf', sha256=uuid4().hex, size_bytes=1,
                status='ready', page_count=1, processed_pages=1, attention_pages=0))
            await session.flush()
            session.add(AnalysisRun(id=rid, guide_id=gid, status='complete', version=1,
                config={'provider':'manual'}, payload={'rules':[], 'coverage':[
                    {'page':1,'outcome':'no_rules','note':'Synthetic coverage'}],
                    'warnings':[], 'batches':[], 'pending_batches':[]}))
        comparison = (await self.client.get(f'/api/analysis/{rid}/comparison')).json()
        stable_id = original['payload']['rules'][0]['stable_id']
        self.assertEqual(comparison['retained_other_guide_ids'], [stable_id])
        self.assertEqual(comparison['missing'], [])
        body = dict(version=1, actor='Publisher', note='Synthetic coverage', name='Combined',
            effective_date='2026-02-01', scope='Cartons and transportation', coverage_confirmed=True,
            impact_confirmed=True, decisions={stable_id:'retire'}, base_release_id=original['id'])
        await self.send('POST', f'/api/analysis/{rid}/publish', body, 422)
        body['decisions'] = {}
        combined = await self.send('POST', f'/api/analysis/{rid}/publish', body)
        self.assertEqual(combined['payload']['rules'], original['payload']['rules'])
        self.assertEqual(combined['payload']['decisions'], {stable_id:'retain'})
        # Editing the packaging contribution of a combined release stays on its source guide.
        draft = await self.send('POST', f'/api/releases/{combined["id"]}/draft',
            {'request_id':str(uuid4()),'actor':'Editor','guide_id':str(self.gid)})
        self.assertEqual(draft['guide_id'], str(self.gid))
        self.assertEqual(len(draft['payload']['rules']), 1)

    async def test_release_draft_preserves_approval_identity_and_original(self):
        original, publish = await self.published_fixture()
        url = f'/api/releases/{original["id"]}/draft'
        body = {'request_id': str(uuid4()), 'actor': 'Editor'}
        await self.send('POST', url, {**body, 'actor': '  '}, 422)
        draft = await self.send('POST', url, body)
        self.assertEqual(await self.send('POST', url, body), draft)
        self.assertEqual(draft['status'], 'complete')
        self.assertEqual(draft['config']['source_release_id'], original['id'])
        self.assertEqual(draft['payload']['pending_batches'], [])
        self.assertEqual(draft['payload']['batches'], [])
        candidate = draft['payload']['rules'][0]
        old = original['payload']['rules'][0]
        self.assertEqual(candidate['id'], old['stable_id'])
        self.assertEqual(candidate['review'], old['review'])
        self.assertEqual(candidate['status'], 'approved')
        workflow = (await self.client.get(f'/api/guides/{self.gid}/workflow')).json()
        self.assertEqual(workflow['active_release_id'], original['id'])
        endpoint = f'/api/analysis/{draft["id"]}/rules/{candidate["id"]}'
        draft = await self.send('PUT', endpoint, dict(version=draft['version'], actor='Editor',
            action='save', note='Clarify title', spec=rule(title='Updated title').model_dump(mode='json')))
        self.assertEqual(draft['payload']['rules'][0]['status'], 'pending')
        self.assertIsNone(draft['payload']['rules'][0]['review'])
        update = {**publish, 'version': draft['version'], 'base_release_id': original['id'], 'name': 'Updated'}
        await self.send('POST', f'/api/analysis/{draft["id"]}/publish', update, 409)
        draft = await self.send('PUT', endpoint, dict(version=draft['version'], actor='Editor', action='approve'))
        update['version'] = draft['version']
        await self.send('POST', f'/api/analysis/{draft["id"]}/publish',
            {**update, 'decisions': {candidate['id']: 'retain'}}, 422)
        updated = await self.send('POST', f'/api/analysis/{draft["id"]}/publish', update)
        self.assertEqual(len(updated['payload']['rules']), 1)
        self.assertEqual(updated['payload']['rules'][0]['stable_id'], old['stable_id'])
        self.assertEqual(updated['payload']['rules'][0]['spec']['title'], 'Updated title')
        exported = (await self.client.get(f'/api/releases/{original["id"]}/export')).json()
        self.assertEqual(exported['payload'], original['payload'])
        # A draft request ID cannot be reused for a different source release.
        await self.send('POST', f'/api/releases/{updated["id"]}/draft', body, 409)

    async def test_unpublish_stale_guard_restore_and_edit_after_unpublishing(self):
        original, publish = await self.published_fixture()
        url = f'/api/releases/{original["id"]}/unpublish'
        body = dict(expected_active_id=original['id'], actor='Reviewer', note='Correcting requirements')
        await self.send('POST', url, {**body, 'expected_active_id': None}, 409)
        await self.send('POST', url, {**body, 'note': '  '}, 422)
        await self.send('POST', url, body)
        await self.send('POST', url, body, 409)
        workflow = (await self.client.get(f'/api/guides/{self.gid}/workflow')).json()
        self.assertIsNone(workflow['active_release_id'])
        self.assertEqual(workflow['runs'][0]['status'], 'published')
        self.assertEqual(workflow['releases'][0]['payload'], original['payload'])
        await self.send('POST', f'/api/releases/{original["id"]}/activate',
            {**body, 'expected_active_id': None})
        await self.send('POST', url, body)
        draft = await self.send('POST', f'/api/releases/{original["id"]}/draft',
            dict(request_id=str(uuid4()), actor='Editor'))
        updated = await self.send('POST', f'/api/analysis/{draft["id"]}/publish',
            {**publish, 'version': draft['version'], 'base_release_id': None})
        self.assertEqual(updated['payload']['rules'][0]['stable_id'], original['payload']['rules'][0]['stable_id'])
        # Unpublishing the old release cannot clear a newly active version.
        await self.send('POST', url, body, 409)

    async def test_release_draft_validates_retained_rule_against_original_guide(self):
        original, _ = await self.published_fixture()
        other_gid = uuid4()
        async with self.sessions.begin() as session:
            # Simulate a release retaining a rule from an older guide.
            session.add(Guide(id=other_gid, retailer_id=self.retailer, title='Newer guide',
                filename='new.pdf', sha256=uuid4().hex, size_bytes=1, status='ready',
                page_count=1, processed_pages=1, attention_pages=0))
            await session.flush()
            session.add(GuidePage(guide_id=other_gid, page_index=0, text='Different source text.',
                text_status='extracted', image_status='ready'))
            run = await session.get(AnalysisRun, self.rid)
            run.guide_id = other_gid
        draft = await self.send('POST', f'/api/releases/{original["id"]}/draft',
            dict(request_id=str(uuid4()), actor='Editor'))
        candidate = draft['payload']['rules'][0]
        self.assertEqual(draft['guide_id'], str(other_gid))
        self.assertEqual(candidate['source_guide_id'], str(self.gid))
        edited = await self.send('PUT', f'/api/analysis/{draft["id"]}/rules/{candidate["id"]}',
            dict(version=draft['version'], actor='Editor', action='save_and_approve',
                 note='Clarify title', spec=rule(title='Original source retained').model_dump(mode='json')))
        self.assertEqual(edited['payload']['rules'][0]['status'], 'approved')

    async def test_typed_delivery_publication_export_and_revision(self):
        from test_delivery import mapped
        response=await self.client.get('/api/rule-types')
        self.assertEqual(response.status_code,200)
        self.assertIn('carton.po_mixing',[entry['id'] for entry in response.json()])
        spec=mapped().model_dump(mode='json')
        run=await self.send('POST',f'/api/analysis/{self.rid}/rules',{'version':1,'actor':'Reviewer','spec':spec})
        candidate=run['payload']['rules'][0]
        await self.send('POST',f'/api/analysis/{self.rid}/classify',{
            'version':run['version'],'actor':'Reviewer','revisions':{candidate['id']:1},
            'purpose':'shipment_validation','operational_category':'electronic_documents_edi',
            'consumption_points':['asn_generation']},422)
        run=await self.send('PUT',f'/api/analysis/{self.rid}/rules/{candidate["id"]}',{
            'version':run['version'],'actor':'Reviewer','action':'approve'})
        release=await self.send('POST',f'/api/analysis/{self.rid}/publish',{
            'version':run['version'],'actor':'Reviewer','note':'Synthetic coverage',
            'name':'Delivery fixture','effective_date':'2026-01-01','scope':'Synthetic cartons only',
            'coverage_confirmed':True,'impact_confirmed':True,'decisions':{},'base_release_id':None})
        url=f'/api/releases/{release["id"]}/delivery'
        result=await self.send('POST',url,{'workflow':'mobile_packing','area':'carton_selection',
            'snapshot':{'cartons':[{'id':'c1','weight':{'value':51,'unit':'lb'}},{}]}})
        self.assertTrue(result['routing_complete'])
        self.assertEqual(result['scope'],'Synthetic cartons only')
        self.assertEqual(result['rules'][0]['rule']['spec']['rule_type'],spec['rule_type'])
        self.assertEqual([s['action'] for s in result['rules'][0]['subjects']],['block','needs_information'])
        await self.send('POST',url,{'workflow':'mobile_packing','area':'made_up'},422)
        await self.send('POST',f'/api/releases/{uuid4()}/delivery',{'workflow':'mobile_packing'},404)
        exported=(await self.client.get(f'/api/releases/{release["id"]}/export')).json()
        self.assertEqual(exported['payload']['rules'][0]['spec']['placements'],spec['placements'])
        markdown=await self.client.get(f'/api/releases/{release["id"]}/export?format=markdown')
        self.assertIn('carton_selection; block; enabled=True',markdown.text)

    async def test_delivery_reports_legacy_gaps_and_disabled_placements(self):
        from test_delivery import mapped
        release_id=uuid4()
        def released(identifier,spec):
            return dict(stable_id=identifier,spec=spec.model_dump(mode='json'),source_guide_id=str(self.gid),draft_id=identifier,review={'actor':'Fixture'})
        disabled=mapped(placements=[{'workflow':'mobile_packing','area':'carton_selection','enabled':False,'behavior':'block'}])
        async with self.sessions.begin() as session:
            session.add(RuleRelease(id=release_id,retailer_id=self.retailer,run_id=self.rid,name='Synthetic legacy mix',effective_date=date(2026,1,1),
                payload=dict(rules=[released('legacy',rule()),released('disabled',disabled)],base_release_id=None,decisions={},scope='Synthetic',coverage_note='Fixture',actor='Fixture',run_version=1)))
        result=await self.send('POST',f'/api/releases/{release_id}/delivery',{'workflow':'mobile_packing'})
        self.assertEqual(result['rules'],[])
        self.assertEqual(result['unmapped_rule_ids'],['legacy'])
        self.assertFalse(result['routing_complete'])
        self.assertEqual(result['disabled_placement_count'],1)
        response=await self.client.get(f'/api/releases/{release_id}/rules?consumption_point=mobile_packing')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['rules']),2)

    async def test_catalog_binding_survives_review_classification_release_and_export(self):
        from test_check_catalog import fulfillment
        response=await self.client.get('/api/check-catalog')
        self.assertEqual(response.status_code,200)
        catalog={entry['id']:entry for entry in response.json()}
        self.assertEqual(catalog['po_line_fulfillment']['availability'],'not_implemented')
        spec=fulfillment().model_dump(mode='json')
        run=await self.send('POST',f'/api/analysis/{self.rid}/rules',{'version':1,'actor':'Reviewer','spec':spec})
        candidate=run['payload']['rules'][0]
        run=await self.send('POST',f'/api/analysis/{self.rid}/classify',{
            'version':run['version'],'actor':'Reviewer','revisions':{candidate['id']:1},
            'purpose':'shipment_validation','operational_category':'warehouse_operations',
            'consumption_points':['mobile_packing','mobile_picking']})
        candidate=run['payload']['rules'][0]
        self.assertEqual(candidate['spec']['schema_version'],'1.2')
        self.assertEqual(candidate['spec']['standard_check'],spec['standard_check'])
        self.assertEqual(candidate['check_status']['availability'],'not_implemented')
        await self.send('POST',f'/api/analysis/{self.rid}/bulk-approve',{
            'version':run['version'],'actor':'Reviewer','revisions':{candidate['id']:candidate['revision']}},422)
        run=await self.send('PUT',f'/api/analysis/{self.rid}/rules/{candidate["id"]}',{
            'version':run['version'],'actor':'Reviewer','action':'approve'})
        release=await self.send('POST',f'/api/analysis/{self.rid}/publish',{
            'version':run['version'],'actor':'Reviewer','note':'Synthetic coverage',
            'name':'Catalog fixture','effective_date':'2026-01-01','scope':'Synthetic only',
            'coverage_confirmed':True,'impact_confirmed':True,'decisions':{},'base_release_id':None})
        self.assertEqual(release['payload']['rules'][0]['check_status']['availability'],'not_implemented')
        exported=await self.client.get(f'/api/releases/{release["id"]}/export')
        self.assertEqual(exported.json()['payload']['rules'][0]['spec']['standard_check'],spec['standard_check'])
        markdown=await self.client.get(f'/api/releases/{release["id"]}/export?format=markdown')
        self.assertIn('PO line fulfillment v1',markdown.text)
        self.assertIn('quantity_basis',markdown.text)
        scenario=await self.send('POST','/api/scenarios',{'retailer_id':self.retailer,'name':'Synthetic',
            'raw':{'schema_version':'1.0','shipment':{'fulfilled':True}}})
        evaluation=await self.send('POST',f'/api/scenarios/{scenario["id"]}/evaluate/{release["id"]}',{})
        self.assertEqual(evaluation['items'][0]['outcome'],'cannot_determine')

    async def test_unmapped_standard_requirement_cannot_be_approved(self):
        spec=rule(schema_version='1.2',purpose='general_guidance',verification='human',assertion=None).model_dump(mode='json')
        run=await self.send('POST',f'/api/analysis/{self.rid}/rules',{'version':1,'actor':'Reviewer','spec':spec})
        candidate=run['payload']['rules'][0]
        run=await self.send('POST',f'/api/analysis/{self.rid}/classify',{
            'version':run['version'],'actor':'Reviewer','revisions':{candidate['id']:1},'purpose':'shipment_validation'})
        candidate=run['payload']['rules'][0]
        self.assertEqual(candidate['spec']['schema_version'],'1.2')
        self.assertEqual(candidate['spec']['verification'],'unresolved')
        self.assertEqual(candidate['check_status']['availability'],'needs_mapping')
        await self.send('PUT',f'/api/analysis/{self.rid}/rules/{candidate["id"]}',{
            'version':run['version'],'actor':'Reviewer','action':'approve'},422)

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

    async def test_flagged_rules_can_be_individually_approved_without_notes(self):
        run = await self.add_candidate(1)
        good = run['payload']['rules'][0]['id']
        run = await self.add_candidate(run['version'], rule(title='Unresolved rule', unresolved_questions=['Check applicability']))
        flagged = run['payload']['rules'][1]['id']
        self.assertTrue(run['payload']['rules'][1]['individual_review_reasons'])
        body = {'version': run['version'], 'actor': 'Reviewer'}
        endpoint = f'/api/analysis/{self.rid}/rules/{good}'
        await self.send('PUT', endpoint, {**body, 'action': 'reject'}, 422)
        await self.send('PUT', endpoint, {**body, 'action': 'save', 'spec': rule().model_dump(mode='json')}, 422)
        run = await self.send('PUT', endpoint, {**body, 'action': 'approve'})
        self.assertEqual(run['payload']['rules'][0]['review']['note'], '')
        self.assertEqual(run['payload']['rules'][1]['status'], 'pending')
        body['version'] = run['version']
        endpoint = f'/api/analysis/{self.rid}/rules/{flagged}'
        await self.send('PUT', endpoint, {**body, 'action': 'reject', 'note': '   '}, 422)
        run = await self.send('PUT', endpoint, {**body, 'action': 'approve'})
        approved = run['payload']['rules'][1]
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(approved['review']['note'], '')
        self.assertEqual(approved['review']['actor'], 'Reviewer')
        self.assertEqual(approved['review']['revision'], approved['revision'])
        self.assertTrue(approved['individual_review_reasons'])

    async def test_flagged_rules_can_be_bulk_approved_without_clearing_warnings(self):
        run = await self.add_candidate(1)
        run = await self.add_candidate(run['version'], rule(unresolved_questions=['Check applicability']))
        candidates = run['payload']['rules']
        self.assertTrue(all(r['individual_review_reasons'] for r in candidates))
        approved = await self.send('POST', f'/api/analysis/{self.rid}/bulk-approve', {
            'version': run['version'], 'actor': 'Reviewer',
            'revisions': {r['id']: r['revision'] for r in candidates},
        })
        for before, after in zip(candidates, approved['payload']['rules']):
            self.assertEqual(after['status'], 'approved')
            self.assertEqual(after['spec'], before['spec'])
            self.assertEqual(after['individual_review_reasons'], before['individual_review_reasons'])
            self.assertEqual(after['review']['mode'], 'bulk')
            self.assertEqual(after['review']['note'], '')

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

    async def test_classification_is_atomic_revisioned_and_does_not_approve(self):
        run = await self.add_candidate(1, rule(purpose='unclassified'))
        run = await self.add_candidate(run['version'], rule(title='Onboarding', purpose='unclassified', verification='external_evidence'))
        first, second = run['payload']['rules']
        url = f'/api/analysis/{self.rid}/classify'
        body = {'version': run['version'], 'actor': 'Reviewer', 'purpose': 'general_guidance',
                'revisions': {first['id']: 1, second['id']: 1}}
        await self.send('POST', url, {**body, 'version': 1}, 409)
        await self.send('POST', url, {**body, 'revisions': {first['id']: 1, str(uuid4()): 1}}, 404)
        await self.send('POST', url, {**body, 'revisions': {first['id']: 1, second['id']: 99}}, 409)
        await self.send('PUT', f'/api/analysis/{self.rid}/rules/{first["id"]}',
            {'version': run['version'], 'actor': 'Reviewer', 'action': 'approve', 'note': 'Cannot bypass missing classification'}, 422)
        classified = await self.send('POST', url, body)
        for candidate in classified['payload']['rules']:
            self.assertEqual(candidate['revision'], 2)
            self.assertEqual(candidate['status'], 'pending')
            self.assertIsNone(candidate['review'])
            self.assertEqual(candidate['spec']['purpose'], 'general_guidance')
        self.assertEqual(classified['payload']['rules'][0]['spec']['evidence'], first['spec']['evidence'])
        self.assertEqual(classified['payload']['rules'][1]['spec']['verification'], 'external_evidence')
        audits = (await self.client.get(f'/api/audit/{self.rid}')).json()
        self.assertEqual(len([a for a in audits if a['action'] == 'rule_classified']), 2)
        approved = await self.send('POST', f'/api/analysis/{self.rid}/bulk-approve',
            {'version': classified['version'], 'actor': 'Reviewer', 'revisions': {first['id']: 2, second['id']: 2}})
        await self.send('POST', url, {**body, 'version': approved['version'], 'revisions': {first['id']: 2}}, 409)
        edited = await self.send('PUT', f'/api/analysis/{self.rid}/rules/{first["id"]}',
            {'version': approved['version'], 'actor': 'Reviewer', 'action': 'save', 'note': 'Weight applies to each shipment',
             'spec': rule(purpose='shipment_validation').model_dump(mode='json')})
        self.assertEqual(edited['payload']['rules'][0]['status'], 'pending')
        self.assertIsNone(edited['payload']['rules'][0]['review'])

    async def test_full_categorization_resolves_missing_dimensions_even_when_use_unchanged(self):
        run = await self.add_candidate(1, rule(purpose='general_guidance', operational_category='unclassified', consumption_points=[]))
        run = await self.add_candidate(run['version'], rule(title='Second rule', purpose='general_guidance', operational_category='unclassified', consumption_points=[]))
        first, second = run['payload']['rules']
        url = f'/api/analysis/{self.rid}/classify'
        body = {'version': run['version'], 'actor': 'Reviewer', 'purpose': 'general_guidance',
                'operational_category': 'business_administration',
                'consumption_points': ['supplier_management', 'supplier_onboarding'],
                'revisions': {first['id']: 1, second['id']: 1}}
        for invalid in ({'operational_category': 'unclassified'}, {'operational_category': 'invented'},
                        {'consumption_points': []}, {'consumption_points': None},
                        {'consumption_points': ['invented']},
                        {'consumption_points': ['supplier_management', 'supplier_management']}):
            await self.send('POST', url, {**body, **invalid}, 422)
        await self.send('POST', url, {k: v for k, v in body.items() if k != 'operational_category'}, 422)
        await self.send('POST', url, {**body, 'revisions': {first['id']: 1, second['id']: 99}}, 409)
        async with self.sessions() as session:
            unchanged = await session.get(AnalysisRun, self.rid)
            self.assertEqual([r['revision'] for r in unchanged.payload['rules']], [1, 1])
            self.assertTrue(all(workflow_api.needs_classification(r['spec']) for r in unchanged.payload['rules']))
        categorized = await self.send('POST', url, body)
        for candidate in categorized['payload']['rules']:
            self.assertEqual(candidate['revision'], 2)
            self.assertEqual(candidate['status'], 'pending')
            self.assertIsNone(candidate['review'])
            self.assertEqual(candidate['spec']['purpose'], 'general_guidance')
            self.assertEqual(candidate['spec']['operational_category'], 'business_administration')
            self.assertEqual(candidate['spec']['consumption_points'], ['supplier_management', 'supplier_onboarding'])
            self.assertFalse(workflow_api.needs_classification(candidate['spec']))
            self.assertEqual(candidate['spec']['evidence'], first['spec']['evidence'])
        repeated = await self.send('POST', url, {**body, 'version': categorized['version'],
                                  'consumption_points': list(reversed(body['consumption_points'])),
                                  'revisions': {first['id']: 2, second['id']: 2}})
        self.assertEqual([r['revision'] for r in repeated['payload']['rules']], [2, 2])
        audits = (await self.client.get(f'/api/audit/{self.rid}')).json()
        self.assertEqual(len([a for a in audits if a['action'] == 'rule_classified']), 2)

    async def test_guidance_remains_in_release_exports_but_not_shipment_results(self):
        run = await self.add_candidate(1, rule(title='Respond to OpenText onboarding invitation', purpose='general_guidance',
                                              verification='external_evidence', assertion=None))
        candidate = run['payload']['rules'][0]['id']
        run = await self.send('PUT', f'/api/analysis/{self.rid}/rules/{candidate}',
            {'version': run['version'], 'actor': 'Reviewer', 'action': 'approve'})
        release = await self.send('POST', f'/api/analysis/{self.rid}/publish',
            {'version': run['version'], 'actor': 'Reviewer', 'note': 'Fixture coverage verified', 'name': 'Guidance',
             'effective_date': '2026-01-01', 'scope': 'New supplier onboarding', 'coverage_confirmed': True,
             'impact_confirmed': True, 'decisions': {}, 'base_release_id': None})
        self.assertEqual(release['payload']['rules'][0]['spec']['purpose'], 'general_guidance')
        exported = await self.client.get(f'/api/releases/{release["id"]}/export?format=markdown')
        self.assertIn('Use: general_guidance', exported.text)
        self.assertIn('Respond to OpenText', exported.text)
        scenario = await self.send('POST', '/api/scenarios', {'retailer_id': self.retailer, 'name': 'Shipment',
                                   'raw': {'schema_version': '1.0', 'shipment': {}, 'cartons': []}})
        evaluation = await self.send('POST', f'/api/scenarios/{scenario["id"]}/evaluate/{release["id"]}', {})
        self.assertEqual(evaluation['guidance_count'], 1)
        self.assertEqual(evaluation['items'], [])
        self.assertEqual(sum(evaluation['counts'].values()), 0)
        history = (await self.client.get(f'/api/scenarios/{scenario["id"]}/evaluations')).json()
        self.assertEqual(history[0]['guidance_count'], 1)

    async def seed_classification(self, count=1):
        ids = [str(uuid4()) for _ in range(count)]
        job_id = str(uuid4())
        async with self.sessions.begin() as session:
            run = await session.get(AnalysisRun, self.rid)
            data = deepcopy(run.payload)
            data['rules'] = [{'id': rid, 'revision': 1, 'status': 'pending', 'spec': rule(title=f'Rule {i}', purpose='unclassified').model_dump(mode='json'),
                              'source_guide_id': str(self.gid), 'review': None, 'evidence_issues': []} for i, rid in enumerate(ids)]
            data['classification_job'] = {'id': job_id, 'status': 'queued', 'provider': 'anthropic', 'model': 'test', 'actor': 'Reviewer',
                'pending': [{'id': rid, 'revision': 1} for rid in ids], 'total': count, 'processed': 0, 'applied': 0, 'skipped': 0, 'batches': [], 'error': None}
            run.payload = data
        return job_id, ids

    async def test_auto_classification_batches_resume_without_repeating_accepted_work(self):
        from routing_guides.classification_provider import Classification, ClassifiedOutput
        job_id, ids = await self.seed_classification(41)
        def result(rids):
            return ClassifiedOutput([Classification(id=rid, purpose='general_guidance', operational_category='business_administration', consumption_points=['supplier_management'], reason='Supplier administration.') for rid in rids], 'test-model', {'input_tokens': 100})
        with patch.object(classification_jobs, 'classify', AsyncMock(side_effect=[result(ids[:40]), ProviderFailure('Temporary problem')])) as mocked:
            await classification_jobs.run_classification(self.rid, job_id)
            self.assertEqual(mocked.await_count, 2)
        async with self.sessions() as session:
            saved = await session.get(AnalysisRun, self.rid)
            self.assertEqual(saved.payload['classification_job']['status'], 'failed')
            self.assertEqual(saved.payload['classification_job']['processed'], 40)
            self.assertTrue(all(r['status'] == 'pending' for r in saved.payload['rules']))
            self.assertEqual(saved.payload['rules'][-1]['spec']['purpose'], 'unclassified')
        with patch.object(classification_jobs, 'classify', AsyncMock(return_value=result(ids[-1:]))) as mocked:
            await classification_jobs.run_classification(self.rid, job_id)
            await classification_jobs.run_classification(self.rid, job_id)
            self.assertEqual(mocked.await_count, 1)
            self.assertEqual([r['id'] for r in mocked.call_args.args[2]], ids[-1:])
        async with self.sessions() as session:
            saved = await session.get(AnalysisRun, self.rid)
            self.assertEqual(saved.payload['classification_job']['status'], 'complete')
            self.assertEqual(saved.payload['classification_job']['applied'], 41)
            self.assertEqual(saved.payload['rules'][0]['revision'], 2)
            self.assertEqual(saved.payload['rules'][0]['classification']['method'], 'ai')
            self.assertEqual(saved.payload['rules'][0]['spec']['assertion'], rule().model_dump(mode='json')['assertion'])
        audits = (await self.client.get(f'/api/audit/{self.rid}')).json()
        self.assertEqual(len([a for a in audits if a['action'] == 'rule_auto_classified']), 41)

    async def test_auto_classification_preserves_human_edits_during_model_call(self):
        from routing_guides.classification_provider import Classification, ClassifiedOutput
        job_id, ids = await self.seed_classification()
        async def provider(*args):
            async with self.sessions.begin() as session:
                run = await session.get(AnalysisRun, self.rid)
                data = deepcopy(run.payload)
                data['rules'][0]['spec']['purpose'] = 'shipment_validation'
                data['rules'][0]['revision'] = 2
                run.payload, run.version = data, run.version+1
            return ClassifiedOutput([Classification(id=ids[0], purpose='general_guidance', operational_category='business_administration', consumption_points=['supplier_management'], reason='Proposed category')], 'test', {})
        with patch.object(classification_jobs, 'classify', provider):
            await classification_jobs.run_classification(self.rid, job_id)
        async with self.sessions() as session:
            run = await session.get(AnalysisRun, self.rid)
            self.assertEqual(run.payload['rules'][0]['spec']['purpose'], 'shipment_validation')
            self.assertEqual(run.payload['rules'][0]['revision'], 2)
            self.assertEqual(run.payload['classification_job']['skipped'], 1)
            self.assertEqual(run.payload['classification_job']['applied'], 0)

    async def test_cancelled_classification_discards_inflight_result(self):
        from routing_guides.classification_provider import Classification, ClassifiedOutput
        job_id, ids = await self.seed_classification()
        async def provider(*args):
            await self.send('POST', f'/api/analysis/{self.rid}/cancel-classification', {'version': 1, 'actor': 'Reviewer'})
            return ClassifiedOutput([Classification(id=ids[0], purpose='general_guidance', operational_category='business_administration', consumption_points=['supplier_management'], reason='Proposed category')], 'test', {})
        with patch.object(classification_jobs, 'classify', provider):
            await classification_jobs.run_classification(self.rid, job_id)
        async with self.sessions() as session:
            run = await session.get(AnalysisRun, self.rid)
            self.assertEqual(run.payload['rules'][0]['spec']['purpose'], 'unclassified')
            self.assertEqual(run.payload['classification_job']['status'], 'cancelled')

    async def test_backfill_taxonomy_preserves_existing_rule_use_and_evidence(self):
        from routing_guides.classification_provider import Classification, ClassifiedOutput
        job_id, ids = await self.seed_classification()
        async with self.sessions.begin() as session:
            run = await session.get(AnalysisRun, self.rid)
            data = deepcopy(run.payload)
            spec = data['rules'][0]['spec']
            spec.update(purpose='shipment_validation', schema_version='1.0')
            spec.pop('operational_category')
            spec.pop('consumption_points')
            original = deepcopy(spec)
            run.payload = data
        output = ClassifiedOutput([Classification(id=ids[0], purpose='general_guidance', operational_category='warehouse_operations', consumption_points=['mobile_packing'], reason='Carton packing requirement.')], 'test', {})
        with patch.object(classification_jobs, 'classify', AsyncMock(return_value=output)):
            await classification_jobs.run_classification(self.rid, job_id)
        async with self.sessions() as session:
            run = await session.get(AnalysisRun, self.rid)
            candidate = run.payload['rules'][0]
            self.assertEqual(candidate['status'], 'pending')
            self.assertEqual(candidate['revision'], 2)
            self.assertEqual(candidate['spec']['purpose'], 'shipment_validation')
            self.assertEqual(candidate['spec']['operational_category'], 'warehouse_operations')
            self.assertEqual(candidate['spec']['consumption_points'], ['mobile_packing'])
            self.assertEqual(candidate['spec']['evidence'], original['evidence'])
            self.assertEqual(candidate['spec']['assertion'], original['assertion'])

    async def test_missing_taxonomy_cannot_be_approved_even_with_note(self):
        run = await self.add_candidate(1, rule(operational_category='unclassified', consumption_points=[]))
        candidate = run['payload']['rules'][0]
        await self.send('PUT', f'/api/analysis/{self.rid}/rules/{candidate["id"]}',
            {'version': run['version'], 'actor': 'Reviewer', 'action': 'approve', 'note': 'Cannot bypass classification'}, 422)
        await self.send('POST', f'/api/analysis/{self.rid}/bulk-approve',
            {'version': run['version'], 'actor': 'Reviewer', 'revisions': {candidate['id']: 1}}, 422)

    async def test_consumer_endpoint_separates_asn_from_packing_and_reports_legacy_gaps(self):
        run = await self.add_candidate(1, rule())
        run = await self.add_candidate(run['version'], rule(title='ASN contents', operational_category='electronic_documents_edi', consumption_points=['asn_generation', 'edi_transmission']))
        approved = await self.send('POST', f'/api/analysis/{self.rid}/bulk-approve',
            {'version': run['version'], 'actor': 'Reviewer', 'revisions': {r['id']: r['revision'] for r in run['payload']['rules']}})
        release = await self.send('POST', f'/api/analysis/{self.rid}/publish',
            {'version': approved['version'], 'actor': 'Reviewer', 'note': 'Synthetic scope', 'name': 'Consumer test', 'effective_date': '2026-01-01', 'scope': 'Synthetic rules', 'coverage_confirmed': True, 'impact_confirmed': True, 'decisions': {}, 'base_release_id': None})
        url = f'/api/releases/{release["id"]}/rules'
        packed = (await self.client.get(url, params={'consumption_point': 'mobile_packing'})).json()
        self.assertEqual([r['spec']['title'] for r in packed['rules']], ['Carton weight'])
        self.assertTrue(packed['routing_complete'])
        asn = (await self.client.get(url, params={'consumption_point': 'asn_generation'})).json()
        self.assertEqual([r['spec']['title'] for r in asn['rules']], ['ASN contents'])
        mismatch = (await self.client.get(url, params={'consumption_point': 'asn_generation', 'operational_category': 'warehouse_operations'})).json()
        self.assertEqual(mismatch['rules'], [])
        self.assertEqual((await self.client.get(url, params={'consumption_point': 'unknown'})).status_code, 422)
        self.assertEqual((await self.client.get(f'/api/releases/{uuid4()}/rules', params={'consumption_point': 'mobile_packing'})).status_code, 404)
        # Simulate an immutable pre-upgrade release in this rollback-only fixture.
        async with self.sessions.begin() as session:
            stored = await session.get(RuleRelease, release['id'])
            data = deepcopy(stored.payload)
            data['rules'][1]['spec'].pop('operational_category')
            data['rules'][1]['spec'].pop('consumption_points')
            stored.payload = data
        legacy = (await self.client.get(url, params={'consumption_point': 'asn_generation'})).json()
        self.assertEqual(legacy['rules'], [])
        self.assertEqual(legacy['unclassified_rule_count'], 1)
        self.assertFalse(legacy['routing_complete'])

    async def test_credentials_are_masked_and_cross_origin_write_rejected(self):
        with patch('routing_guides.connections.get_settings',return_value=SimpleNamespace(storage_root=Path(self.temp.name),anthropic_api_key=SimpleNamespace(get_secret_value=lambda:''),anthropic_model='',openai_api_key=SimpleNamespace(get_secret_value=lambda:''),openai_model='',jev_api_key=SimpleNamespace(get_secret_value=lambda:''),jev_model='jev-1.14.0')):
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

    async def test_ignore_is_audited_reversible_and_excluded_from_publication(self):
        from sqlalchemy import select
        from routing_guides.models import AuditEvent
        spec = rule().model_dump(mode='json')
        run = await self.send('POST', f'/api/analysis/{self.rid}/rules', {'version':1,'actor':'Reviewer','spec':spec})
        candidate = run['payload']['rules'][0]
        path = f'/api/analysis/{self.rid}/rules/{candidate["id"]}'
        ignored = await self.send('PUT', path, {'version':run['version'],'actor':'Reviewer','action':'ignore'})
        stored = ignored['payload']['rules'][0]
        self.assertEqual(stored['status'], 'ignored')
        self.assertEqual(stored['revision'], candidate['revision'])
        self.assertEqual(stored['spec'], spec)
        self.assertEqual(ignored['payload']['coverage'], run['payload']['coverage'])
        await self.send('PUT', path, {'version':run['version'],'actor':'Reviewer','action':'restore'},409)
        await self.send('PUT', path, {'version':ignored['version'],'actor':'Reviewer','action':'approve'},422)
        restored = await self.send('PUT', path, {'version':ignored['version'],'actor':'Reviewer','action':'restore'})
        self.assertEqual(restored['payload']['rules'][0]['status'], 'pending')
        self.assertEqual(restored['payload']['rules'][0]['spec'], spec)
        await self.send('PUT', path, {'version':restored['version'],'actor':'Reviewer','action':'restore'},422)
        ignored = await self.send('PUT', path, {'version':restored['version'],'actor':'Reviewer','action':'ignore'})
        release = await self.send('POST', f'/api/analysis/{self.rid}/publish', {
            'version':ignored['version'],'actor':'Reviewer','note':'Synthetic ignored proposal',
            'name':'Ignore fixture','effective_date':'2026-01-01','scope':'Synthetic',
            'coverage_confirmed':True,'impact_confirmed':True,'decisions':{},'base_release_id':None})
        self.assertEqual(release['payload']['rules'], [])
        # Publication freezes the draft, including its ignored decisions.
        await self.send('PUT', path, {'version':ignored['version'],'actor':'Reviewer','action':'restore'},409)
        async with self.sessions() as session:
            events = (await session.scalars(select(AuditEvent).where(AuditEvent.entity_id==self.rid))).all()
            ignored_event = next(e for e in events if e.action=='ignore')
            self.assertEqual(ignored_event.payload['before']['status'], 'pending')
            self.assertEqual(ignored_event.payload['after']['status'], 'ignored')
            self.assertTrue(any(e.action=='restore' for e in events))

    async def test_inline_correction_and_approval_are_atomic(self):
        spec = rule().model_dump(mode='json')
        run = await self.send('POST', f'/api/analysis/{self.rid}/rules', {'version':1,'actor':'Reviewer','spec':spec})
        candidate = run['payload']['rules'][0]
        path = f'/api/analysis/{self.rid}/rules/{candidate["id"]}'
        changed = {**spec, 'title':'Updated carton weight'}
        bad_source = {**changed, 'evidence':[{'page':1,'quote':'A source quote that does not exist','kind':'text'}]}
        await self.send('PUT', path, {'version':run['version'],'actor':'Reviewer','note':'Updated evidence during rule review.',
            'action':'save_and_approve','spec':bad_source},422)
        async with self.sessions() as session:
            saved = await session.get(AnalysisRun, self.rid)
            self.assertEqual(saved.version, run['version'])
            self.assertEqual(saved.payload['rules'][0]['spec'], spec)
            self.assertEqual(saved.payload['rules'][0]['status'], 'pending')
        approved = await self.send('PUT', path, {'version':run['version'],'actor':'Reviewer','note':'Updated title during rule review.',
            'action':'save_and_approve','spec':changed})
        current = approved['payload']['rules'][0]
        self.assertEqual(current['status'], 'approved')
        self.assertEqual(current['revision'], 2)
        self.assertEqual(current['review']['revision'], 2)
        self.assertEqual(current['spec']['title'], changed['title'])
        await self.send('PUT', path, {'version':run['version'],'actor':'Reviewer','note':'Stale edit',
            'action':'save_and_approve','spec':spec},409)

    async def test_inline_approval_cannot_bypass_classification_or_ignore(self):
        spec = rule().model_dump(mode='json')
        run = await self.send('POST', f'/api/analysis/{self.rid}/rules', {'version':1,'actor':'Reviewer','spec':spec})
        path = f'/api/analysis/{self.rid}/rules/{run["payload"]["rules"][0]["id"]}'
        await self.send('PUT', path, {'version':run['version'],'actor':'Reviewer','note':'Updated use',
            'action':'save_and_approve','spec':{**spec,'purpose':'unclassified'}},422)
        ignored = await self.send('PUT', path, {'version':run['version'],'actor':'Reviewer','action':'ignore'})
        await self.send('PUT', path, {'version':ignored['version'],'actor':'Reviewer','note':'Try approving ignored',
            'action':'save_and_approve','spec':spec},422)
