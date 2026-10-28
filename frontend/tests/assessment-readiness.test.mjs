import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/assessmentReadiness.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {assessmentState,readyForApprovalSelection,reviewProgress,reviewFailure} = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);

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


test('preparation progress never mixes results from a prior run',()=>{
  const rules=[{status:'pending',revision:1,assessment:{job_id:'old',outcome:'ready'}},
    {status:'pending',revision:1,assessment:{job_id:'old',check_failed:true}}];
  const progress=reviewProgress(rules,{id:'new',status:'running',phase:'resolve',resolution_failed:3});
  assert.equal(progress.checked,0);
  assert.deepEqual(progress.visible,[]);
  assert.equal(progress.currentFailures,3);
});
test('checking counts only current results and retries preparation failures too',()=>{
  const rules=[{status:'pending',revision:1,assessment:{job_id:'old',outcome:'ready'}},
    {status:'pending',revision:1,assessment:{job_id:'new',outcome:'ready'}},
    {status:'pending',revision:1,resolution:{revision:1,failed:true}}];
  const progress=reviewProgress(rules,{id:'new',status:'running',phase:'assess',failed:0});
  assert.equal(progress.checked,1);
  assert.equal(progress.retryCount,1);
  assert.equal(progress.currentFailures,0);
});

test('unsupported model requests explain the blocker instead of recommending the same retry', () => {
  for (const job of [
    {reason:'provider_configuration', error:'The selected model cannot accept the request.'},
    {error:'The selected model rejected the extraction tool settings. Smaller batches will not resolve this; the provider adapter needs a compatible request.'},
  ]) {
    const failure = reviewFailure(job);
    assert.equal(failure.canContinue, false);
    assert.match(failure.message, /application update/);
    assert.doesNotMatch(failure.message, /tool settings|provider adapter/);
  }
});
test('transient failures show the saved cause and allow continuing', () => {
  const message = 'Provider temporarily unavailable or rate limited. Retry this run.';
  assert.deepEqual(reviewFailure({error:message}), {message,canContinue:true});
  assert.equal(reviewFailure({}).canContinue, true);
  for (const reason of ['configuration_required','version_changed','repeated_invalid_responses'])
    assert.equal(reviewFailure({reason}).canContinue, false);
});
