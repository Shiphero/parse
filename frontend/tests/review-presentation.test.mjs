import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/reviewPresentation.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {reviewPresentation} = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const rule={status:'pending',revision:1,individual_review_reasons:['Possible duplicate or conflict: review matching titles together.']};
const identity=[{section:'reviewer',label:'Enter your reviewer name'}];

test('preparation explains the lock without asking for disabled fields or identity',()=>{
  const result=reviewPresentation({...rule,resolution:{revision:1,failed:false}},[...identity,{section:'classification',label:'Choose a category'}],false,{id:'job',status:'running',phase:'resolve'});
  assert.equal(result.kind,'working');
  assert.match(result.title,/Rule details prepared/);
  assert.match(result.detail,/No action needed/);
});
test('reviewer identity and same-title cautions do not become missing rule fields',()=>{
  const result=reviewPresentation(rule,identity,true);
  assert.equal(result.kind,'unchecked');
  assert.equal(result.title,'No missing fields identified');
});
test('only a fresh result from this run is actionable during checking',()=>{
  const assessed={...rule,assessment:{outcome:'ready',job_id:'job'},assessment_stale:false};
  const job={id:'job',status:'running',phase:'assess'};
  assert.equal(reviewPresentation(assessed,[],true,job).kind,'ready');
  assert.equal(reviewPresentation({...assessed,assessment_stale:true},[],true,job).kind,'working');
  assert.equal(reviewPresentation({...assessed,assessment:{outcome:'ready',job_id:'old'}},[],true,job).kind,'working');
});
test('actual missing fields are counted separately from identity and incomplete checks',()=>{
  const result=reviewPresentation(rule,[...identity,{section:'instruction',field:'instruction',label:'Add the instruction'}],true);
  assert.equal(result.title,'1 field needs information');
  assert.equal(reviewPresentation({...rule,assessment:{outcome:'needs_review',check_failed:true}},[],true).label,'Check incomplete');
});
test('saved decisions and read-only versions do not request a new decision',()=>{
  assert.equal(reviewPresentation({...rule,status:'approved'},identity,false).kind,'approved');
  assert.equal(reviewPresentation({...rule,status:'ignored'},identity,false).kind,'ignored');
  assert.equal(reviewPresentation(rule,identity,false).kind,'readonly');
});
test('automatic decisions are explained without requesting another approval',()=>{
  const approved=reviewPresentation({...rule,status:'approved',review:{mode:'automatic'}},identity,true);
  assert.equal(approved.label,'Auto-approved');
  assert.match(approved.detail,/No action is needed/);
  const duplicate=reviewPresentation({...rule,status:'ignored',review:{mode:'automatic_duplicate'}},identity,true);
  assert.equal(duplicate.label,'Duplicate set aside');
  assert.match(duplicate.detail,/restore this rule/);
});
test('remaining findings identify the problem rather than a generic flag',()=>{
  const result=reviewPresentation({...rule,assessment:{outcome:'needs_review',issues:[{code:'duplicate_conflict'}]}},[],true);
  assert.equal(result.label,'Conflicting requirements');
  assert.match(result.detail,/Leave the rule pending/);
});
