import { useRemote } from './api';
import type { RuleSpec, RuleTypeDefinition, CheckDefinition } from './api';
import { consumptionPointLabels } from './ruleTaxonomy';

type Placement = NonNullable<RuleSpec['placements']>[number];
export const behaviorLabels:Record<Placement['behavior'],string>={display:'Display instructions',confirm:'Request confirmation',warn:'Warn on check failure',block:'Block on check failure'};

export default function RuleDeliveryEditor({spec,onChange}:{spec:RuleSpec;onChange:(value:RuleSpec)=>void}) {
  const catalog=useRemote<RuleTypeDefinition[]>('/api/rule-types');
  const checks=useRemote<CheckDefinition[]>('/api/check-catalog');
  const selected=catalog.data?.find(entry=>entry.id===spec.rule_type?.id);
  const automatic=spec.purpose==='shipment_validation'&&checks.data?.some(check=>check.id===spec.standard_check?.check_id&&check.availability==='implemented');
  const placements=spec.placements||[];
  const changePlacements=(value:Placement[])=>onChange({...spec,placements:value,consumption_points:[...new Set(value.map(p=>p.workflow))].sort()});
  return <div className="delivery-settings">
    {catalog.error&&<p className="error">{catalog.error} <button className="text-button" onClick={catalog.reload}>Retry</button></p>}
    <label>Standard rule type<select disabled={!catalog.data} value={spec.rule_type?.id||''} onChange={e=>{
      const type=catalog.data?.find(entry=>entry.id===e.target.value);
      if(!type){onChange({...spec,rule_type:null,placements:[],...(spec.schema_version==='1.2'&&spec.purpose==='shipment_validation'&&!spec.standard_check?{verification:'unresolved',assertion:null}:{})});return;}
      const subject=type.subjects.includes(spec.subject)?spec.subject:type.subjects[0] as RuleSpec['subject'];
      const keepCheck=spec.standard_check&&type.check_ids.includes(spec.standard_check.check_id)&&subject===spec.subject;
      onChange({...spec,schema_version:'1.2',rule_type:{id:type.id,version:1},subject,
        operational_category:type.category,placements:type.default_placements,
        consumption_points:[...new Set(type.default_placements.map(p=>p.workflow))].sort(),
        standard_check:keepCheck?spec.standard_check:null,assertion:null,
        verification:keepCheck?spec.verification:type.check_ids.length?'unresolved':'human'});
    }}><option value="">Needs rule type mapping</option>{catalog.data?.map(entry=><option key={entry.id} value={entry.id}>{entry.label} · v{entry.version}</option>)}</select></label>
    <p className="field-hint">Changing type resets workflow defaults and incompatible checks.</p>
    {selected&&<>
      <table className="placement-table"><thead><tr><th>Use</th><th>Workflow / area</th><th>Behavior</th><th/></tr></thead><tbody>{placements.map((p,i)=>{
        const area=selected.allowed_placements.find(a=>a.workflow===p.workflow&&a.area===p.area);
        return <tr key={`${p.workflow}:${p.area}`}><td><input type="checkbox" aria-label={`Use in ${consumptionPointLabels[p.workflow]} / ${area?.label||p.area}`} checked={p.enabled??true} onChange={e=>changePlacements(placements.map((old,j)=>j===i?{...old,enabled:e.target.checked}:old))}/></td>
          <td>{consumptionPointLabels[p.workflow]}<small style={{display:'block'}}>{area?.label||p.area}</small></td>
          <td><select aria-label={`Behavior in ${consumptionPointLabels[p.workflow]} / ${p.area}`} value={p.behavior||'display'} onChange={e=>changePlacements(placements.map((old,j)=>j===i?{...old,behavior:e.target.value as Placement['behavior']}:old))}>{Object.entries(behaviorLabels).map(([id,label])=><option key={id} value={id} disabled={(id==='warn'||id==='block')&&(!automatic||id==='block'&&!['required','prohibited'].includes(spec.obligation))}>{label}</option>)}</select></td>
          <td><button className="text-button" disabled={placements.length===1} onClick={()=>changePlacements(placements.filter((_,j)=>i!==j))}>Remove</button></td></tr>;
      })}</tbody></table>
      <label>Add workflow area<select value="" onChange={e=>{const a=selected.allowed_placements.find(a=>`${a.workflow}:${a.area}`===e.target.value);if(a)changePlacements([...placements,{workflow:a.workflow,area:a.area,enabled:true,behavior:'display'}]);}}><option value="">Choose an area…</option>{selected.allowed_placements.filter(a=>!placements.some(p=>p.workflow===a.workflow&&p.area===a.area)).map(a=><option key={`${a.workflow}:${a.area}`} value={`${a.workflow}:${a.area}`}>{consumptionPointLabels[a.workflow]} → {a.label}</option>)}</select></label>
      <details className="editor-help"><summary>About this type & behaviors</summary><p>{selected.description}</p><p>Turning an area off omits it from consumer delivery, not from shipment validation. Warnings and blocking require an implemented automatic check.</p></details>
      {placements.some(p=>!p.enabled)&&<p className="notice">Disabled placements are omitted from consumer delivery. They do not waive the requirement.</p>}
    </>}
  </div>;
}
