import { useEffect, useRef, useState } from 'react';
import StandardCheckEditor from './StandardCheckEditor';
import RuleDeliveryEditor from './RuleDeliveryEditor';
import ConditionBuilder, { describeCondition } from './ConditionBuilder';
import { SourceImage, RegionPicker } from './SourceImage';
import { operationalCategoryLabels, consumptionPointOptions } from './ruleTaxonomy';
import { resolveCheckStatus, rulePurposeLabels, verificationSummary } from './rulePurpose';
import RuleUsage from './RuleUsage';
import { useRemote } from './api';
import type { Candidate, RuleSpec, RuleTypeDefinition, CheckDefinition } from './api';
import { reviewTasks } from './reviewReadiness';
import type { ReviewSection } from './reviewReadiness';

export const blankRule = (): RuleSpec => ({schema_version:'1.2',standard_check:null,rule_type:null,placements:[],operational_category:'unclassified',consumption_points:[],purpose:'unclassified', title:'',instruction:'',subject:'carton',obligation:'required',verification:'unresolved',applicability_text:'',applicability:null,exceptions:[],assertion:null,evidence:[{page:1,quote:'',kind:'text',region:null}],unresolved_questions:[]});

export function Evidence({guideId, spec, collapsibleImage=false}: {guideId:string;spec:RuleSpec;collapsibleImage?:boolean}) {
  const [chosen, setChosen] = useState(0);
  const evidence = spec.evidence[chosen] || spec.evidence[0];
  return <aside className="rule-evidence"><h3>Source evidence</h3><div className="evidence-tabs">{spec.evidence.map((e,i)=><button key={i} className={chosen===i?'selected':''} onClick={()=>setChosen(i)}>Page {e.page}</button>)}</div>{evidence && <><blockquote>{evidence.quote}</blockquote>{evidence.region&&<SourceImage key={`${evidence.page}:${chosen}`} guideId={guideId} evidence={evidence}/>}<span className="muted">{evidence.kind==='visual'?'Visual evidence — verify against the page':'Text excerpt'} · PDF page {evidence.page}</span><a href={`/api/guides/${guideId}/original`} target="_blank" rel="noreferrer">Open original PDF</a>{collapsibleImage?<details className="source-page-preview"><summary>View original page & placement</summary><div className="evidence-image"><img loading="lazy" src={`/api/guides/${guideId}/pages/${evidence.page-1}/image`} alt={`Evidence on PDF page ${evidence.page}`}/>{evidence.region && <span className="evidence-region" style={{left:`${evidence.region[0]*100}%`,top:`${evidence.region[1]*100}%`,width:`${evidence.region[2]*100}%`,height:`${evidence.region[3]*100}%`}}/>}</div></details>:<div className="evidence-image"><img loading="lazy" src={`/api/guides/${guideId}/pages/${evidence.page-1}/image`} alt={`Evidence on PDF page ${evidence.page}`}/>{evidence.region && <span className="evidence-region" style={{left:`${evidence.region[0]*100}%`,top:`${evidence.region[1]*100}%`,width:`${evidence.region[2]*100}%`,height:`${evidence.region[3]*100}%`}}/>}</div>}</>}</aside>;
}

type ReviewControls = {
  actor:string; onActorChange:(value:string)=>void; editable:boolean; error:string;
  onApprove:(spec:RuleSpec,note:string,changed:boolean)=>Promise<void>;
  onDecision:(kind:'ignore'|'restore'|'reject',note:string)=>Promise<void>;
  onDirtyChange:(dirty:boolean)=>void; onNext?:()=>void; onVariant?:()=>void;
};

export default function RuleEditor({candidate,initial,guideId,onSave,onCancel,busy,review}: {candidate?:Candidate;initial?:RuleSpec;guideId:string;onSave:(spec:RuleSpec,note:string)=>Promise<void>;onCancel:()=>void;busy:boolean;review?:ReviewControls}) {
  const [spec,setSpec] = useState<RuleSpec>(candidate?.spec || initial || blankRule());
  const types=useRemote<RuleTypeDefinition[]>('/api/rule-types');
  const checks=useRemote<CheckDefinition[]>('/api/check-catalog');
  const ruleType=types.data?.find(t=>t.id===spec.rule_type?.id);
  const workflows=consumptionPointOptions.filter(([id])=>spec.consumption_points?.includes(id as NonNullable<RuleSpec['consumption_points']>[number]));
  const classificationSummary=[ruleType?.label||(spec.rule_type?.id||'Type not mapped'),...workflows.map(([,label])=>label)].join(' · ');
  const checkStatus=resolveCheckStatus(spec,checks.data,types.data);
  const verification=verificationSummary(spec,checkStatus);
  const verificationDescription=`${verification.label} · ${verification.detail}`;
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
  const [rejecting,setRejecting] = useState(false);
  const sections = useRef<Partial<Record<ReviewSection, HTMLElement | null>>>({});
  const dirty = !!candidate && JSON.stringify(spec)!==JSON.stringify(candidate.spec);
  const tasks = review && candidate ? reviewTasks(spec,candidate,review.actor,types.data||[],checks.data||[]) : [];
  if (review && advanced!==null) tasks.push({section:'advanced',label:'Apply or discard the JSON changes'});
  const initialTasks = useRef(tasks);
  useEffect(()=>{review?.onDirtyChange(dirty||advanced!==null);},[dirty,advanced]);
  const goTo = (section:ReviewSection) => {
    const element=sections.current[section];
    if(element instanceof HTMLDetailsElement) element.open=true;
    element?.scrollIntoView({block:'center',behavior:'smooth'});
    element?.querySelector<HTMLElement>('input,select,textarea,button')?.focus({preventScroll:true});
  };
  const correction = () => `Updated ${Object.keys(spec).filter(key=>JSON.stringify(spec[key as keyof RuleSpec])!==JSON.stringify(candidate?.spec[key as keyof RuleSpec])).map(key=>key.replaceAll('_',' ')).join(', ')} during rule review.`;
  const approve = async () => {
    if(tasks.length){goTo(tasks[0].section);return;}
    await review?.onApprove(spec,dirty?correction():'',dirty);
  };
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
    await onSave(spec,review?correction():note);} catch(e){setError((e as Error).message);} };
  return <div className={review?'guided-rule-review':''}>
    {review&&candidate&&<div className={`review-readiness ${tasks.length?'needs-input':'ready'}`}>
      <div><strong>{!review.editable?'Read-only review':candidate.status==='ignored'?'Ignored rule':tasks.length?`${tasks.length} ${tasks.length===1?'item':'items'} to complete before approval`:dirty?'Changes ready for review':candidate.status==='approved'?'Approved':'Ready for your approval'}</strong>
        <span>{candidate.status==='ignored'?'Excluded from publication. Restore it to continue.':tasks.length?'Complete the fields below. Select an item to go straight to it.':'Compare the instruction with its source, then approve. No decision note is required.'}</span></div>
      {tasks.length>0&&candidate.status!=='ignored'&&<ul>{tasks.map((task,i)=><li key={i}><button className="text-button" onClick={()=>goTo(task.section)}>{task.label} <span aria-hidden="true">→</span></button></li>)}</ul>}
    </div>}
    <div className="rule-review-grid compact-rule-editor"><div className="rule-form">
    <fieldset className="review-editable-fields" disabled={busy||!!review&&(!review.editable||candidate?.status==='ignored')}>
    <RuleUsage spec={spec} status={checkStatus} ruleType={ruleType} onEditVerification={()=>goTo('verification')} onEditWorkflows={()=>goTo('classification')}/>
    <div ref={el=>{sections.current.instruction=el;}}>
    <div className="editor-heading"><h3>{review?'Instruction':candidate?'Edit rule':'New rule'}</h3><span className="muted">{review?(dirty?'Unsaved changes':'Edit directly below'):'Changes need review'}</span></div>
    <label>Title<input maxLength={250} value={spec.title} onChange={e=>set('title',e.target.value)}/></label>
    <label>Instruction<textarea rows={3} value={spec.instruction} onChange={e=>set('instruction',e.target.value)}/></label>

    </div>
    <details ref={el=>{sections.current.classification=el;}} open={review&&initialTasks.current.some(t=>t.section==='classification')} className="editor-section"><summary><span>Where it’s used & rule type</span><small title={classificationSummary}>{classificationSummary}</small></summary><div className="editor-section-body">
      <RuleDeliveryEditor spec={spec} onChange={setSpec} compact={!!review}/>
      {!spec.rule_type&&<>
        <label>Category<select value={spec.operational_category||'unclassified'} onChange={e=>set('operational_category',e.target.value as RuleSpec['operational_category'])}>{Object.entries(operationalCategoryLabels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
        <div className="workflow-selection"><span className="field-label">Used in</span><div className="workflow-chips">{workflows.length?workflows.map(([id,label])=><span className="workflow-chip" key={id}>{label}<button type="button" aria-label={`Remove ${label}`} onClick={()=>set('consumption_points',(spec.consumption_points||[]).filter(p=>p!==id))}>×</button></span>):<span className="muted">No workflows assigned</span>}</div>
          <label>Add workflow<select value="" onChange={e=>{if(e.target.value)set('consumption_points',[...(spec.consumption_points||[]),e.target.value as NonNullable<RuleSpec['consumption_points']>[number]]);}}><option value="">Choose a workflow…</option>{consumptionPointOptions.filter(([id])=>!spec.consumption_points?.includes(id as NonNullable<RuleSpec['consumption_points']>[number])).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
        </div>
      </>}
      <div className="form-row"><label>Rule use<select disabled={spec.rule_type?.id==='general.guidance'} value={spec.purpose||'unclassified'} onChange={e=>setSpec(s=>({...s,purpose:e.target.value as RuleSpec['purpose'],...(s.schema_version==='1.2'&&!s.standard_check&&!s.rule_type&&e.target.value==='shipment_validation'?{verification:'unresolved',assertion:null}:{})}))}>{Object.entries(rulePurposeLabels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
      <label>Obligation<select value={spec.obligation} onChange={e=>set('obligation',e.target.value as RuleSpec['obligation'])}>{['required','prohibited','recommended','informational'].map(v=><option key={v}>{v}</option>)}</select></label></div>
      <p className="field-hint">Guidance appears in instructions; shipment rules can also be checked.</p>
    </div></details>

    <details ref={el=>{sections.current.conditions=el;}} open={review&&initialTasks.current.some(t=>t.section==='conditions')} className="editor-section"><summary><span>When it applies</span><small>{spec.applicability_text||describeCondition(spec.applicability)}{spec.exceptions?.length?` · ${spec.exceptions.length} exception(s)`:''}</small></summary><div className="editor-section-body">
      <label>Subject<select value={spec.subject} onChange={e=>set('subject',e.target.value as RuleSpec['subject'])}>{['shipment','order','pallet','carton','item','label','document'].map(v=><option key={v}>{v}</option>)}</select></label>
      <ConditionBuilder subject={spec.subject} value={spec.applicability} onChange={value=>{set('applicability',value);set('applicability_text',describeCondition(value));}}/>
      <label>Applies when (description)<textarea rows={2} value={spec.applicability_text} onChange={e=>set('applicability_text',e.target.value)}/></label>
      {spec.exceptions?.map((exception,i)=><p className="field-hint" key={i}><strong>Exception:</strong> {exception.description}</p>)}
      {!!spec.exceptions?.length&&<p className="field-hint">Edit exception conditions in Advanced JSON.</p>}
    </div></details>

    <details ref={el=>{sections.current.verification=el;}} open={review&&initialTasks.current.some(t=>t.section==='verification')} className="editor-section"><summary><span>How it’s verified</span><small title={verificationDescription}>{verificationDescription}</small></summary><div className="editor-section-body">
      {spec.rule_type?.id==='general.guidance'&&<p className="field-hint">Reference only. General guidance is displayed as instructions and is excluded from shipment checks.</p>}
      {spec.purpose!=='general_guidance'&&<StandardCheckEditor spec={spec} onChange={setSpec}/>}
      {spec.rule_type?.id!=='general.guidance'&&!spec.standard_check&&(spec.schema_version!=='1.2'||spec.purpose==='general_guidance')&&<label>Verification method<select value={spec.verification} onChange={e=>set('verification',e.target.value as RuleSpec['verification'])}><option value="data">Automatic data check</option><option value="human">Human inspection</option><option value="external_evidence">External evidence required</option><option value="unresolved">Unresolved interpretation</option></select></label>}
      {spec.verification==='data'&&!spec.standard_check&&spec.schema_version!=='1.2'&&<ConditionBuilder subject={spec.subject} label="Automatic check passes when" value={spec.assertion} onChange={value=>set('assertion',value)}/>}
    </div></details>

    <details ref={el=>{sections.current.evidence=el;}} open={review&&initialTasks.current.some(t=>t.section==='evidence')} className="editor-section"><summary><span>Sources & images</span><small>{spec.evidence.length} reference(s) · PDF page {[...new Set(spec.evidence.map(e=>e.page))].join(', ')}</small></summary><div className="editor-section-body">
{review&&!!candidate?.evidence_issues?.length&&<div className="evidence-warning">{candidate.evidence_issues.map((issue,i)=><p key={i}>{issue}</p>)}<small>Corrected references are checked again when you save.</small></div>}
{spec.evidence.map((e,i)=><div className="reference-fields" key={i}><div className="form-row"><label>PDF page<input type="number" min="1" value={e.page} onChange={v=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,page:Number(v.target.value)}:old))}/></label><label>Evidence type<select value={e.kind} onChange={v=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,kind:v.target.value as 'text'|'visual'}:old))}><option value="text">Exact text excerpt</option><option value="visual">Visual evidence</option></select></label></div><label>Excerpt or description<textarea value={e.quote} onChange={v=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,quote:v.target.value}:old))}/></label><details><summary>Select diagram / image region</summary><RegionPicker key={`${i}:${e.page}`} guideId={guideId} evidence={e} onChange={region=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,region}:old))}/></details><button className="text-button" disabled={spec.evidence.length===1} onClick={()=>set('evidence',spec.evidence.filter((_,j)=>j!==i))}>Remove reference</button></div>)}<button className="text-button" onClick={()=>set('evidence',[...spec.evidence,{page:1,quote:'',kind:'text',region:null}])}>Add reference</button>
    </div></details>
    <details ref={el=>{sections.current.advanced=el;}} className="editor-section advanced"><summary><span>Advanced JSON</span><small>{advanced!==null?'Unapplied changes':'Conditions, exceptions & unresolved questions'}</small></summary><div className="editor-section-body"><p className="muted">True must mean compliance. Use field paths, explicit measurement units, and the supported expression operators. Leave the assertion null for human checks. Unresolved conditions remain Cannot determine.</p><textarea aria-label="Rule conditions JSON" className="json-editor" rows={15} value={advanced??advancedValue} onChange={e=>changeAdvanced(e.target.value)}/>{advanced!==null&&<><p className="notice">Apply or discard the JSON changes before saving the rule.</p>{advancedError&&<p className="error">{advancedError}</p>}<div className="action-row"><button className="secondary" disabled={!!advancedError} onClick={applyAdvanced}>Apply JSON</button><button className="text-button" onClick={()=>{setAdvanced(null);setAdvancedError('');}}>Discard JSON changes</button></div></>}</div></details>

    </fieldset>
    {review&&candidate&&<details className="review-cautions"><summary>Review cautions & history{candidate.individual_review_reasons.length?` · ${candidate.individual_review_reasons.length} cautions`:''}</summary>
      <p className="field-hint">These call for your judgment; they do not all block individual approval. Approval records the requirement, not proof that a shipment complies.</p>
      <ul>{candidate.individual_review_reasons.map((reason,i)=><li key={i}>{reason}</li>)}</ul>
      {!!candidate.evidence_issues?.length&&<ul>{candidate.evidence_issues.map((issue,i)=><li key={i}>{issue}</li>)}</ul>}
      {spec.unresolved_questions?.map((q,i)=><p key={i}>{q}</p>)}
      {candidate.review&&<p>Last decision by {String(candidate.review.actor)}{candidate.review.note?`: ${String(candidate.review.note)}`:''}</p>}
      {!!candidate.classification?.reason&&<p>{String(candidate.classification.reason)}</p>}
      {candidate.carried_from_release_id&&<p>Approval carried forward from the previous release.</p>}
    </details>}
    {!review&&!!spec.unresolved_questions?.length&&<p className="notice">{spec.unresolved_questions.join(' ')}</p>}
    {advanced!==null&&<p className="notice">Apply or discard your Advanced JSON changes before saving.</p>}
    {error&&<div className="error" role="alert">{error}</div>}
    </div><Evidence guideId={guideId} spec={spec} collapsibleImage/></div>
    {review&&candidate?<div className="review-action-dock">
      {review.error&&<div className="error review-submit-error" role="alert"><strong>Could not save this decision</strong><p>{review.error}</p></div>}
      <div className="review-action-identity" ref={el=>{sections.current.reviewer=el;}}>
        <label>Reviewer<input value={review.actor} onChange={e=>review.onActorChange(e.target.value)} placeholder="Your name" autoComplete="name" disabled={busy||!review.editable}/></label>
        <span>{dirty?'Changes will be saved with this decision.':tasks.length?tasks[0].label:candidate.status==='ignored'?'Restore this rule before making changes.':'No approval note required.'}</span>
      </div>
      {rejecting&&<label className="rejection-note">Why reject this rule?<input autoFocus value={note} onChange={e=>setNote(e.target.value)} placeholder="A reason is required for rejection" disabled={busy}/></label>}
      <div className="review-action-buttons">
        {candidate.status==='ignored'?<button className="secondary" disabled={busy||!review.editable} onClick={()=>review.actor.trim()?review.onDecision('restore',''):goTo('reviewer')}>Restore to review</button>:<>
          <button className="text-button" disabled={busy||dirty||advanced!==null||!review.editable} title={dirty?'Save or discard changes first':'Exclude from publication; you can restore it later'} onClick={()=>review.actor.trim()?review.onDecision('ignore',''):goTo('reviewer')}>Ignore rule</button>
          <button className="text-button" disabled={busy||dirty||advanced!==null||!review.editable} onClick={()=>{if(!rejecting){setRejecting(true);return;}if(!review.actor.trim()){goTo('reviewer');return;}if(note.trim())void review.onDecision('reject',note);}}>{rejecting?'Confirm rejection':'Reject…'}</button>
        </>}
        {rejecting&&<button className="text-button" onClick={()=>{setRejecting(false);setNote('');}}>Cancel rejection</button>}
        {review.onVariant&&<button className="text-button" disabled={busy||dirty||advanced!==null||!review.editable} onClick={review.onVariant}>Create variant</button>}
        <div className="review-action-primary">
          {dirty||advanced!==null?<><button className="secondary" disabled={busy} onClick={()=>{setSpec(candidate.spec);setAdvanced(null);setError('');setNote('');}}>Discard changes</button><button className="secondary" disabled={busy||advanced!==null||!review.editable} onClick={()=>review.actor.trim()?save():goTo('reviewer')}>Save draft</button></>:review.onNext&&<button className="secondary" disabled={busy} onClick={review.onNext}>Next rule →</button>}
          {candidate.status!=='ignored'&&<button className="primary" disabled={busy||!review.editable||candidate.status==='approved'&&!dirty} onClick={approve}>{busy?'Saving…':tasks.length?`Complete ${tasks.length} ${tasks.length===1?'item':'items'}`:dirty?'Save & approve':candidate.status==='approved'?'Approved':'Approve rule'}</button>}
        </div>
      </div>
    </div>:<div className="editor-save-bar">

      {candidate&&<label>Reason for change<input value={note} onChange={e=>setNote(e.target.value)} placeholder="Briefly describe your correction" required/></label>}
      {error&&<div className="error" role="alert">{error}</div>}
      <div className="editor-save-actions"><small className="muted">{candidate?'Saving clears prior approval.':'Saved as a draft.'}</small><button className="secondary" onClick={onCancel}>Cancel</button><button className="primary" onClick={save} disabled={busy||advanced!==null||!!candidate&&!note.trim()}>{busy?'Saving…':'Save draft'}</button></div>
    </div>}
  </div>;
}
