import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/assessmentReadiness.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {assessmentState,readyForApprovalSelection} = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);

test('an outdated ready recommendation is never counted or filtered as ready', () => {
  assert.equal(assessmentState({assessment:{outcome:'ready'},assessment_stale:true}), 'stale');
  assert.equal(assessmentState({assessment:{outcome:'ready'},assessment_stale:false}), 'ready');
});
test('missing assessment and assessed uncertainty are different states', () => {
  assert.equal(assessmentState({}), 'unassessed');
  assert.equal(assessmentState({assessment:{outcome:'needs_review'}}), 'needs_review');
  assert.equal(assessmentState({assessment:{outcome:'needs_correction'}}), 'needs_correction');
});
test('bulk-ready selection uses current results and never bypasses source errors or failed checks', () => {
  const candidate={status:'pending',evidence_issues:[],individual_review_reasons:['Review exceptions individually.'],assessment:{outcome:'ready'},assessment_stale:false};
  assert.equal(readyForApprovalSelection(candidate),true);
  for(const change of [{assessment_stale:true},{status:'approved'},{evidence_issues:['Mismatched quote']},
    {assessment:{outcome:'needs_review'}},{assessment:{outcome:'ready',check_failed:true}}])
    assert.equal(readyForApprovalSelection({...candidate,...change}),false);
  assert.equal(readyForApprovalSelection({...candidate,assessment:null}),false);
});
