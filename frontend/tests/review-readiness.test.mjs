import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/reviewReadiness.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {reviewTasks} = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const spec = {schema_version:'1.2',title:'Carton weight',instruction:'Keep cartons under 50 lb.',purpose:'shipment_validation',
  operational_category:'warehouse_operations',consumption_points:['mobile_packing'],applicability_text:'All cartons',
  evidence:[{page:1,quote:'50 lb'}],verification:'unresolved',assertion:null,standard_check:null,rule_type:null};
const tasks = (value=spec,actor='Reviewer',types=[],checks=[],candidate={spec})=>reviewTasks(value,candidate,actor,types,checks);

test('lists every missing classification field and reviewer instead of only the first blocker',()=>{
  const value={...spec,purpose:'unclassified',operational_category:'unclassified',consumption_points:[]};
  assert.deepEqual(tasks(value,'').map(t=>t.section),['classification','classification','classification','reviewer']);
});
test('shipment mappings block; general guidance and legacy requirements do not require a new check',()=>{
  assert.deepEqual(tasks().map(t=>t.section),['verification']);
  assert.deepEqual(tasks({...spec,purpose:'general_guidance'}),[]);
  assert.deepEqual(tasks({...spec,schema_version:'1.1'}),[]);
});
test('manual catalog instructions do not request an invented automatic check',()=>{
  const value={...spec,rule_type:{id:'pallet.wrapping'},verification:'human'};
  assert.deepEqual(tasks(value,'Reviewer',[{id:'pallet.wrapping',check_ids:[]}]),[]);
});
test('reference requirements preserve shipment purpose without demanding an unavailable check',()=>{
  assert.deepEqual(tasks({...spec,execution_mode:'reference_only'}),[]);
  assert.deepEqual(tasks({...spec,execution_mode:'reference_only'},'').map(t=>t.section),['reviewer']);
});
test('empty or out-of-range typed parameters are actionable even for an unavailable validator',()=>{
  const check={id:'test',availability:'not_implemented',parameters_schema:{required:['percent','basis'],properties:{percent:{type:'number',minimum:0,maximum:100},basis:{enum:['packed','shipped']}}}};
  const value={...spec,standard_check:{check_id:'test',parameters:{percent:101,basis:''}}};
  assert.equal(tasks(value,'Reviewer',[],[check]).length,2);
  assert.deepEqual(tasks({...value,standard_check:{check_id:'test',parameters:{percent:100,basis:'packed'}}},'Reviewer',[],[check]),[]);
});
test('source issues link to evidence and corrected evidence is submitted for server revalidation',()=>{
  const value={...spec,purpose:'general_guidance'};
  const candidate={spec:value,evidence_issues:['Text does not match']};
  assert.deepEqual(tasks(value,'Reviewer',[],[],candidate).map(t=>t.section),['evidence']);
  assert.deepEqual(tasks({...value,evidence:[{page:2,quote:'Corrected quote'}]},'Reviewer',[],[],candidate),[]);
});
