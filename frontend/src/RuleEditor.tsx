import { useState } from 'react';
import StandardCheckEditor from './StandardCheckEditor';
import RuleDeliveryEditor from './RuleDeliveryEditor';
import ConditionBuilder, { describeCondition } from './ConditionBuilder';
import { SourceImage, RegionPicker } from './SourceImage';
import { operationalCategoryLabels, consumptionPointOptions } from './ruleTaxonomy';
import { rulePurposeLabels } from './rulePurpose';
import type { Candidate, RuleSpec } from './api';

export const blankRule = (): RuleSpec => ({schema_version:'1.2',standard_check:null,rule_type:null,placements:[],operational_category:'unclassified',consumption_points:[],purpose:'unclassified', title:'',instruction:'',subject:'carton',obligation:'required',verification:'unresolved',applicability_text:'',applicability:null,exceptions:[],assertion:null,evidence:[{page:1,quote:'',kind:'text',region:null}],unresolved_questions:[]});

export function Evidence({guideId, spec, collapsibleImage=false}: {guideId:string;spec:RuleSpec;collapsibleImage?:boolean}) {
  const [chosen, setChosen] = useState(0);
  const evidence = spec.evidence[chosen] || spec.evidence[0];
  return <aside className="rule-evidence"><h3>Source evidence</h3><div className="evidence-tabs">{spec.evidence.map((e,i)=><button key={i} className={chosen===i?'selected':''} onClick={()=>setChosen(i)}>Page {e.page}</button>)}</div>{evidence && <><blockquote>{evidence.quote}</blockquote>{evidence.region&&<SourceImage key={`${evidence.page}:${chosen}`} guideId={guideId} evidence={evidence}/>}<span className="muted">{evidence.kind==='visual'?'Visual evidence — verify against the page':'Text excerpt'} · PDF page {evidence.page}</span><a href={`/api/guides/${guideId}/original`} target="_blank" rel="noreferrer">Open original PDF</a>{collapsibleImage?<details className="source-page-preview"><summary>View original page & placement</summary><div className="evidence-image"><img loading="lazy" src={`/api/guides/${guideId}/pages/${evidence.page-1}/image`} alt={`Evidence on PDF page ${evidence.page}`}/>{evidence.region && <span className="evidence-region" style={{left:`${evidence.region[0]*100}%`,top:`${evidence.region[1]*100}%`,width:`${evidence.region[2]*100}%`,height:`${evidence.region[3]*100}%`}}/>}</div></details>:<div className="evidence-image"><img loading="lazy" src={`/api/guides/${guideId}/pages/${evidence.page-1}/image`} alt={`Evidence on PDF page ${evidence.page}`}/>{evidence.region && <span className="evidence-region" style={{left:`${evidence.region[0]*100}%`,top:`${evidence.region[1]*100}%`,width:`${evidence.region[2]*100}%`,height:`${evidence.region[3]*100}%`}}/>}</div>}</>}</aside>;
}

export default function RuleEditor({candidate,initial,guideId,onSave,onCancel,busy}: {candidate?:Candidate;initial?:RuleSpec;guideId:string;onSave:(spec:RuleSpec,note:string)=>Promise<void>;onCancel:()=>void;busy:boolean}) {
  const [spec,setSpec] = useState<RuleSpec>(candidate?.spec || initial || blankRule());
  const [advanced,setAdvanced] = useState<string|null>(null);
  const [advancedError,setAdvancedError] = useState('');
  const advancedValue = JSON.stringify({applicability:spec.applicability, exceptions:spec.exceptions, assertion:spec.assertion, unresolved_questions:spec.unresolved_questions},null,2);
  const changeAdvanced = (text:string) => {
    setAdvanced(text);
    try {
      const value=JSON.parse(text);
      if (!value || typeof value!=='object' || Array.isArray(value) || !['applicability','assertion','exceptions','unresolved_questions'].every(key=>key in value)) throw new Error('Include applicability, assertion, exceptions and unresolved_questions.');
      if (!Array.isArray(value.exceptions)||!Array.isArray(value.unresolved_questions)) throw new Error('Exceptions and unresolved questions must be arrays.');
      const validateExpression = (expression:unknown,depth=0):void => {
        if (expression===null) return;
        if (depth>16||!expression||typeof expression!=='object'||Array.isArray(expression)) throw new Error('Conditions must be expression objects or null, with at most 16 nested levels.');
        const item=expression as Record<string,unknown>;
        if (typeof item.op!=='string'||!['eq','ne','lt','lte','gt','gte','in','exists','all','any','not','count','sum','unique_count'].includes(item.op)) throw new Error('Unsupported expression operator.');
        if (item.path!=null&&typeof item.path!=='string') throw new Error('Field paths must be text.');
        if (item.children!==undefined&&!Array.isArray(item.children)) throw new Error('Expression children must be an array.');
        for (const child of (item.children||[]) as unknown[]) { if(child===null) throw new Error('A child condition cannot be null.'); validateExpression(child,depth+1); }
      };
      validateExpression(value.applicability); validateExpression(value.assertion);
      for(const exception of value.exceptions) { if(!exception||typeof exception.description!=='string') throw new Error('Each exception needs a description.'); validateExpression(exception.condition??null); }
      if(!value.unresolved_questions.every((question:unknown)=>typeof question==='string')) throw new Error('Unresolved questions must be text.');
      setAdvancedError('');
    } catch(e) {setAdvancedError((e as Error).message);}
  };
  const applyAdvanced = () => {
    if (advanced===null||advancedError) return;
    const value=JSON.parse(advanced);
    setSpec(s=>({...s,applicability:value.applicability,assertion:value.assertion,exceptions:value.exceptions,unresolved_questions:value.unresolved_questions}));
    setAdvanced(null);
  };
  const [error,setError] = useState('');
  const [note,setNote] = useState('');
  const set = <K extends keyof RuleSpec>(key:K,value:RuleSpec[K])=>setSpec(s=>({...s,[key]:value}));
  const save = async () => { try {
    for (const reference of spec.evidence) {
      if (reference.region) {
        const [x,y,w,h]=reference.region;
        if (![x,y,w,h].every(Number.isFinite)||x<0||y<0||w<=0||h<=0||x+w>1||y+h>1) throw new Error('Image bounds must have positive width and height and fit inside the source page.');
      }
    }
    if (spec.standard_check && spec.assertion) throw new Error('Standard checks use catalog parameters. Remove the custom assertion from Advanced JSON.');
    await onSave(spec,note);} catch(e){setError((e as Error).message);} };
  return <div className="rule-review-grid"><div className="rule-form"><h3>{candidate?'Rule builder · edit rule':'Rule builder · new draft'}</h3><p className="muted">Saving creates a new draft revision and clears any prior approval.</p>
    <RuleDeliveryEditor spec={spec} onChange={setSpec}/>
    {!spec.rule_type&&<><label>Operational category<select value={spec.operational_category||'unclassified'} onChange={e=>set('operational_category',e.target.value as RuleSpec['operational_category'])}>{Object.entries(operationalCategoryLabels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
    <fieldset className="consumption-points"><legend>Consumed by</legend><p className="muted">Choose where this rule is enforced or displayed. Do not select a workflow only because it supplies data; ASN requirements normally belong to ASN generation or EDI transmission.</p>{consumptionPointOptions.map(([value,label])=><label className="checkbox-label" key={value}><input type="checkbox" checked={spec.consumption_points?.includes(value as NonNullable<RuleSpec['consumption_points']>[number])||false} onChange={e=>set('consumption_points',e.target.checked?[...(spec.consumption_points||[]),value as NonNullable<RuleSpec['consumption_points']>[number]]:(spec.consumption_points||[]).filter(p=>p!==value))}/>{label}</label>)}</fieldset></>}
    <label>Rule use<select value={spec.purpose||'unclassified'} onChange={e=>setSpec(s=>({...s,purpose:e.target.value as RuleSpec['purpose'],...(s.schema_version==='1.2'&&!s.standard_check&&!s.rule_type&&e.target.value==='shipment_validation'?{verification:'unresolved',assertion:null}:{})}))}>{Object.entries(rulePurposeLabels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label><p className="muted">General guidance stays in the instructions but is excluded from shipment checks. Shipment validation includes automatic checks, physical inspections and shipment evidence.</p>
    <label>Rule title<input value={spec.title} onChange={e=>set('title',e.target.value)}/></label><label>Operational instruction<textarea rows={3} value={spec.instruction} onChange={e=>set('instruction',e.target.value)}/></label>
    <div className="form-row"><label>Subject<select value={spec.subject} onChange={e=>set('subject',e.target.value as RuleSpec['subject'])}>{['shipment','order','pallet','carton','item','label','document'].map(v=><option key={v}>{v}</option>)}</select></label><label>Obligation<select value={spec.obligation} onChange={e=>set('obligation',e.target.value as RuleSpec['obligation'])}>{['required','prohibited','recommended','informational'].map(v=><option key={v}>{v}</option>)}</select></label></div>
    <p className="muted">Choose Cartons as the subject for carton-height rules. Height, width, length and weight refer to each selected subject; shipment.mode refers to the shipment.</p><ConditionBuilder subject={spec.subject} value={spec.applicability} onChange={value=>{set('applicability',value);set('applicability_text',describeCondition(value));}}/><label>Applies when (description)<textarea rows={2} value={spec.applicability_text} onChange={e=>set('applicability_text',e.target.value)}/></label>{spec.purpose!=='general_guidance'&&<StandardCheckEditor spec={spec} onChange={setSpec}/>}{!spec.standard_check&&(spec.schema_version!=='1.2'||spec.purpose==='general_guidance')&&<label>Verification<select value={spec.verification} onChange={e=>set('verification',e.target.value as RuleSpec['verification'])}><option value="data">Automatic data check</option><option value="human">Human inspection</option><option value="external_evidence">External evidence required</option><option value="unresolved">Unresolved interpretation</option></select></label>}
    {spec.verification==='data'&&!spec.standard_check&&spec.schema_version!=='1.2'&&<ConditionBuilder subject={spec.subject} label="Automatic check passes when" value={spec.assertion} onChange={value=>set('assertion',value)}/>}<p className="muted">Conditions select which subjects need this instruction. A matching size does not verify physical label placement; use Human inspection for that.</p><h4>Source references & images</h4>{spec.evidence.map((e,i)=><div className="reference-fields" key={i}><div className="form-row"><label>PDF page<input type="number" min="1" value={e.page} onChange={v=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,page:Number(v.target.value)}:old))}/></label><label>Evidence type<select value={e.kind} onChange={v=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,kind:v.target.value as 'text'|'visual'}:old))}><option value="text">Exact text excerpt</option><option value="visual">Visual evidence</option></select></label></div><label>Excerpt or description<textarea value={e.quote} onChange={v=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,quote:v.target.value}:old))}/></label><details><summary>Select diagram / image region</summary><RegionPicker key={`${i}:${e.page}`} guideId={guideId} evidence={e} onChange={region=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,region}:old))}/></details><button className="text-button" disabled={spec.evidence.length===1} onClick={()=>set('evidence',spec.evidence.filter((_,j)=>j!==i))}>Remove reference</button></div>)}<button className="text-button" onClick={()=>set('evidence',[...spec.evidence,{page:1,quote:'',kind:'text',region:null}])}>Add reference</button>
    <details className="advanced"><summary>Advanced JSON · conditions and exceptions</summary><p className="muted">True must mean compliance. Use field paths, explicit measurement units, and the supported expression operators. Leave the assertion null for human checks. Unresolved conditions remain Cannot determine.</p><textarea aria-label="Rule conditions JSON" className="json-editor" rows={15} value={advanced??advancedValue} onChange={e=>changeAdvanced(e.target.value)}/>{advanced!==null&&<><p className="notice">Apply or discard the JSON changes before saving the rule.</p>{advancedError&&<p className="error">{advancedError}</p>}<div className="action-row"><button className="secondary" disabled={!!advancedError} onClick={applyAdvanced}>Apply JSON</button><button className="text-button" onClick={()=>{setAdvanced(null);setAdvancedError('');}}>Discard JSON changes</button></div></>}</details>
    {candidate&&<label>Correction note<textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="What did you correct and why?" required/></label>}
    {error && <div className="error" role="alert">{error}</div>}<div className="action-row"><button className="secondary" onClick={onCancel}>Cancel</button><button className="primary" onClick={save} disabled={busy||advanced!==null||!!candidate&&!note.trim()}>{busy?'Saving…':'Save draft'}</button></div></div><Evidence guideId={guideId} spec={spec}/></div>;
}
