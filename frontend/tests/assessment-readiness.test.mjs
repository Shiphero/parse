import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/assessmentReadiness.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {assessmentState} = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);

test('an outdated ready recommendation is never counted or filtered as ready', () => {
  assert.equal(assessmentState({assessment:{outcome:'ready'},assessment_stale:true}), 'stale');
  assert.equal(assessmentState({assessment:{outcome:'ready'},assessment_stale:false}), 'ready');
});
test('missing assessment and assessed uncertainty are different states', () => {
  assert.equal(assessmentState({}), 'unassessed');
  assert.equal(assessmentState({assessment:{outcome:'needs_review'}}), 'needs_review');
  assert.equal(assessmentState({assessment:{outcome:'needs_correction'}}), 'needs_correction');
});
