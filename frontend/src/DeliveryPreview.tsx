import { useState } from 'react';
import { jsonRequest, useRemote } from './api';
import type { RuleTypeDefinition, RuleSpec, DeliveryView } from './api';
import { consumptionPointOptions } from './ruleTaxonomy';
import { behaviorLabels } from './RuleDeliveryEditor';
import { SourceImage } from './SourceImage';

type Workflow = NonNullable<RuleSpec['consumption_points']>[number];
export default function DeliveryPreview({releaseId,onClose}:{releaseId:string;onClose:()=>void}) {
  const catalog=useRemote<RuleTypeDefinition[]>('/api/rule-types');
  const [workflow,setWorkflow]=useState<Workflow>('mobile_packing');
  const [area,setArea]=useState('');
  const [raw,setRaw]=useState('{}');
  const [result,setResult]=useState<DeliveryView|null>(null);
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  const areas=[...new Map(catalog.data?.flatMap(t=>t.allowed_placements).filter(a=>a.workflow===workflow).map(a=>[a.area,a])).values()].sort((a,b)=>a.label.localeCompare(b.label));
  const preview=async()=>{setBusy(true);setResult(null);setError('');try{setResult(await jsonRequest<DeliveryView>(`/api/releases/${releaseId}/delivery`,{workflow,area:area||null,snapshot:JSON.parse(raw)}));}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  return <section className="delivery-preview"><div className="section-heading"><h3>Preview consumer delivery</h3><button className="text-button" onClick={onClose}>Close preview</button></div>
    <p className="muted">Read-only preview for this published release. Confirm its scope and effective date. This does not record confirmations or enforce actions in a warehouse application.</p>
    <div className="form-row"><label>Workflow<select value={workflow} disabled={busy} onChange={e=>{setWorkflow(e.target.value as Workflow);setArea('');setResult(null);}}>{consumptionPointOptions.map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label><label>Area<select value={area} disabled={busy} onChange={e=>{setArea(e.target.value);setResult(null);}}><option value="">All areas</option>{areas.map(a=><option key={a.area} value={a.area}>{a.label}</option>)}</select></label></div>
    <label>Canonical shipment facts (JSON)<textarea rows={5} className="json-editor" value={raw} disabled={busy} onChange={e=>{setRaw(e.target.value);setResult(null);}}/></label>
    <button className="text-button" disabled={busy} onClick={()=>{setRaw(JSON.stringify({shipment:{},cartons:[{id:'example-carton',height:{value:8,unit:'in'},weight:{value:20,unit:'lb'}}]},null,2));setResult(null);}}>Use synthetic carton example</button>
    <button className="secondary" disabled={busy} onClick={preview}>{busy?'Resolving…':'Preview delivery'}</button>
    {(error||catalog.error)&&<p className="error">{error||catalog.error}</p>}
    {result&&<><p>{result.rules.length} placements returned · {result.disabled_placement_count} disabled · effective {result.effective_date}</p><p className="muted">Scope: {result.scope}</p>
      {!result.routing_complete&&<p className="notice">{result.unmapped_rule_ids.length} rules in this release still need rule type mapping. An empty result does not mean there are no requirements.</p>}
      {result.rules.map(item=><article key={`${item.rule.stable_id}:${item.placement.area}`}><h4>{item.type_label} · {areas.find(a=>a.area===item.placement.area)?.label||item.placement.area}</h4><p>{item.rule.spec.instruction}</p><small>{behaviorLabels[item.placement.behavior||'display']}</small>
        <ul>{item.subjects.map((subject,i)=><li key={i}><strong>{subject.subject_id}: {subject.action.replaceAll('_',' ')}</strong> · {subject.reason}</li>)}</ul>
        {item.rule.spec.evidence.filter(e=>e.region).map((e,i)=><SourceImage key={i} guideId={item.rule.source_guide_id} evidence={e}/>)}
      </article>)}
      <details><summary>Full delivery JSON</summary><pre>{JSON.stringify(result,null,2)}</pre></details>
    </>}
  </section>;
}
