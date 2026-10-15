import { useRemote } from './api';
import type { RuleSpec, CheckDefinition, RuleTypeDefinition } from './api';

const words = (value:string) => value.replaceAll('_',' ').replace(/^./,letter=>letter.toUpperCase());
const fieldLabels: Record<string,string> = {
  required_percent:'Required fulfillment (%)', quantity_basis:'Compare ordered quantity against',
  order_basis:'Ordered quantity source', maximum_unique_skus:'Maximum distinct SKUs per carton', maximum_unique_pos:'Maximum distinct POs per carton',
  required_checks:'Required label inspections', reconcile_by:'Reconcile ASN by',
};
const optionLabels: Record<string,string> = {lte:'At most (≤)',gte:'At least (≥)',original_order:'Original PO quantities',approved_current_order:'Approved current PO revision'};
type Property = {type?:string;enum?:string[];items?:{enum?:string[]};minimum?:number;maximum?:number;exclusiveMinimum?:number};
type Binding = NonNullable<RuleSpec['standard_check']>;
export const availabilityLabels = {implemented:'Automatic verification',not_implemented:'Automatic verification · unavailable',manual:'Manual verification',external:'External confirmation',needs_mapping:'Verification not configured',legacy:'Existing verification · not mapped',guidance:'Guidance only'};

export default function StandardCheckEditor({spec,onChange}: {spec:RuleSpec;onChange:(spec:RuleSpec)=>void}) {
  const catalog=useRemote<CheckDefinition[]>('/api/check-catalog');
  const types=useRemote<RuleTypeDefinition[]>('/api/rule-types');
  const type=types.data?.find(entry=>entry.id===spec.rule_type?.id);
  const selected=catalog.data?.find(entry=>entry.id===spec.standard_check?.check_id && entry.version===spec.standard_check.version);
  const properties=(selected?.parameters_schema.properties||{}) as Record<string,Property>;
  const parameters=(spec.standard_check?.parameters||{}) as Record<string,unknown>;
  const changeParameter=(key:string,value:unknown)=>onChange({...spec,standard_check:{...spec.standard_check!,parameters:{...parameters,[key]:value}} as Binding});
  if(type&&type.check_ids.length===0)return <fieldset className="condition-builder"><legend>Verification</legend><p className="muted">This standard type uses instructions and evidence; no automatic validator is registered.</p><label>Verification method<select value={spec.verification} onChange={e=>onChange({...spec,verification:e.target.value as RuleSpec['verification'],standard_check:null,assertion:null})}><option value="human">Human inspection</option><option value="external_evidence">External confirmation</option><option value="unresolved">Needs interpretation</option></select></label></fieldset>;
  return <fieldset className="condition-builder standard-check-editor"><legend>Standard verification check</legend>
    {catalog.error&&<p className="error" role="alert">{catalog.error} <button className="text-button" onClick={catalog.reload}>Retry catalog</button></p>}
    <label>Check type<select value={spec.standard_check?.check_id||(spec.schema_version==='1.2'?'':'__legacy')} disabled={!catalog.data} onChange={e=>{
      if(!e.target.value){onChange({...spec,schema_version:'1.2',standard_check:null,verification:'unresolved',assertion:null});return;}
      const check=catalog.data?.find(entry=>entry.id===e.target.value);if(!check)return;
      const fields=check.parameters_schema.properties as Record<string,Property>;
      const empty=Object.fromEntries(Object.entries(fields).map(([key,property])=>[key,property.type==='array'?[]:property.type==='number'||property.type==='integer'?null:'']));
      onChange({...spec,schema_version:'1.2',purpose:'shipment_validation',subject:check.subjects.includes(spec.subject)?spec.subject:check.subjects[0] as RuleSpec['subject'],verification:check.verification,assertion:null,standard_check:{check_id:check.id,version:check.version,parameters:empty} as Binding});
    }}>
      {spec.schema_version!=='1.2'&&!spec.standard_check&&<option value="__legacy">Existing verification (not mapped)</option>}
      <option value="">Needs mapping — select a standard check</option>
      {catalog.data?.filter(check=>!type||type.check_ids.includes(check.id)).map(check=><option key={`${check.id}:${check.version}`} value={check.id}>{check.label} · v{check.version}</option>)}
    </select></label>
    {selected?<>
      <p><strong>{availabilityLabels[selected.availability]}</strong> · Evaluates {selected.subjects.join(' / ')}</p>
      <p className="muted">{selected.description}</p>
      {!selected.subjects.includes(spec.subject)&&<p className="error">Change the subject to {selected.subjects.join(' or ')} for this check.</p>}
      {selected.availability==='not_implemented'&&<p className="notice">You can approve this requirement after review. Scenario validation will report Cannot determine until its validator is implemented.</p>}
      {Object.entries(properties).map(([key,property])=><div key={key}>
        {property.type==='array'?<fieldset className="consumption-points"><legend>{fieldLabels[key]||words(key)}</legend>{property.items?.enum?.map(option=><label className="checkbox-label" key={option}><input type="checkbox" checked={Array.isArray(parameters[key])&&(parameters[key] as string[]).includes(option)} onChange={e=>changeParameter(key,e.target.checked?[...(parameters[key] as string[]||[]),option]:(parameters[key] as string[]||[]).filter(item=>item!==option))}/>{words(option)}</label>)}</fieldset>:
        <label>{fieldLabels[key]||words(key)}{property.enum?<select value={String(parameters[key]??'')} onChange={e=>changeParameter(key,e.target.value)}><option value="" disabled>Choose…</option>{property.enum.map(option=><option key={option} value={option}>{optionLabels[option]||words(option)}</option>)}</select>:
        <input type="number" step={property.type==='integer'?1:'any'} min={property.minimum} max={property.maximum} value={typeof parameters[key]==='number'?parameters[key] as number:''} onChange={e=>changeParameter(key,e.target.value===''?null:Number(e.target.value))}/>}</label>}
      </div>)}
      <details><summary>Required data</summary><ul>{selected.required_data.map(item=><li key={item}>{item}</li>)}</ul></details>
    </>:<p className="muted">{spec.schema_version==='1.2'?'Choose a shared check before approving a shipment requirement. If none fits, keep Needs mapping; new check types must be added to the catalog.':'This existing rule retains its current verification. Map it explicitly to adopt the shared catalog.'}</p>}
  </fieldset>;
}
