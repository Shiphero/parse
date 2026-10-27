import { useEffect, useRef, useState } from 'react';
import { Check, Copy, EyeOff, X } from 'lucide-react';
import StandardCheckEditor from './StandardCheckEditor';
import RuleDeliveryEditor from './RuleDeliveryEditor';
import ConditionBuilder, { describeCondition } from './ConditionBuilder';
import { SourceImage, RegionPicker } from './SourceImage';
import { operationalCategoryLabels, consumptionPointOptions } from './ruleTaxonomy';
import { resolveCheckStatus, rulePurposeLabels, verificationSummary } from './rulePurpose';
import RuleUsage from './RuleUsage';
import { useRemote } from './api';
import type { Candidate, RuleSpec, RuleTypeDefinition, CheckDefinition } from './api';
import AssessmentDetails from './AssessmentDetails';
import ResolutionDetails from './ResolutionDetails';
import { reviewTasks } from './reviewReadiness';
import { reviewPresentation } from './reviewPresentation';
import type { ReviewJob } from './reviewPresentation';
import type { ReviewSection } from './reviewReadiness';

export const blankRule = (): RuleSpec => ({schema_version:'1.2',execution_mode:'standard',standard_check:null,rule_type:null,placements:[],operational_category:'unclassified',consumption_points:[],purpose:'unclassified', title:'',instruction:'',subject:'carton',obligation:'required',verification:'unresolved',applicability_text:'',applicability:null,exceptions:[],assertion:null,evidence:[{page:1,quote:'',kind:'text',region:null}],unresolved_questions:[]});

export function Evidence({guideId, spec, collapsibleImage=false}: {guideId:string;spec:RuleSpec;collapsibleImage?:boolean}) {
  const [chosen, setChosen] = useState(0);
  const evidence = spec.evidence[chosen] || spec.evidence[0];
  return <aside className="rule-evidence"><h3>Source evidence</h3><div className="evidence-tabs">{spec.evidence.map((e,i)=><button key={i} className={chosen===i?'selected':''} onClick={()=>setChosen(i)}>Page {e.page}</button>)}</div>{evidence && <><blockquote>{evidence.quote}</blockquote>{evidence.region&&<SourceImage key={`${evidence.page}:${chosen}`} guideId={guideId} evidence={evidence}/>}<span className="muted">{evidence.kind==='visual'?'Visual evidence — verify against the page':'Text excerpt'} · PDF page {evidence.page}</span><a href={`/api/guides/${guideId}/original`} target="_blank" rel="noreferrer">Open original PDF</a>{collapsibleImage?<details className="source-page-preview"><summary>View original page & placement</summary><div className="evidence-image"><img loading="lazy" src={`/api/guides/${guideId}/pages/${evidence.page-1}/image`} alt={`Evidence on PDF page ${evidence.page}`}/>{evidence.region && <span className="evidence-region" style={{left:`${evidence.region[0]*100}%`,top:`${evidence.region[1]*100}%`,width:`${evidence.region[2]*100}%`,height:`${evidence.region[3]*100}%`}}/>}</div></details>:<div className="evidence-image"><img loading="lazy" src={`/api/guides/${guideId}/pages/${evidence.page-1}/image`} alt={`Evidence on PDF page ${evidence.page}`}/>{evidence.region && <span className="evidence-region" style={{left:`${evidence.region[0]*100}%`,top:`${evidence.region[1]*100}%`,width:`${evidence.region[2]*100}%`,height:`${evidence.region[3]*100}%`}}/>}</div>}</>}</aside>;
}

type ReviewControls = {
  actor:string; onActorChange:(value:string)=>void; editable:boolean; error:string; job?:ReviewJob|null;
  onApprove:(spec:RuleSpec,note:string,changed:boolean)=>Promise<void>;
  onDecision:(kind:'ignore'|'restore'|'reject',note:string)=>Promise<void>;
  onDirtyChange:(dirty:boolean)=>void; onOpenRelated?:(id:string)=>void; onNext?:()=>void; onVariant?:()=>void;
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
  if (review && advanced!==null) tasks.push({section:'advanced',field:'technical',label:'Apply or discard the technical settings changes'});
  const fieldTasks = tasks.filter(task=>task.section!=='reviewer');
  const presentation = review && candidate ? reviewPresentation(candidate,fieldTasks,review.editable,review.job) : null;
  const working = presentation?.kind==='working';
  const [detailsOpen,setDetailsOpen] = useState(!review);
  const showFields = !review || detailsOpen || !!fieldTasks.length && review.editable && !working;
  const initialTasks = useRef(fieldTasks);
  const pendingFocus = useRef<{section:ReviewSection;field?:string}|null>(null);
  useEffect(()=>{review?.onDirtyChange(dirty||advanced!==null);},[dirty,advanced]);
  const focusField = (section:ReviewSection,field?:string) => {
    const element=sections.current[section];
    if(element instanceof HTMLDetailsElement) element.open=true;
    const target=field ? Array.from(element?.querySelectorAll<HTMLElement>('[data-review-field]')||[]).find(node=>node.dataset.reviewField===field) : undefined;
    for(let parent=target?.parentElement;parent&&parent!==element;parent=parent.parentElement) if(parent instanceof HTMLDetailsElement) parent.open=true;
    (target||element)?.scrollIntoView({block:'center',behavior:'smooth'});
    const control=target?.matches('input,select,textarea,button')?target:(target||element)?.querySelector<HTMLElement>('input,select,textarea,button');
    control?.focus({preventScroll:true});
  };
  const goTo = (section:ReviewSection,field?:string) => {
    if(section==='reviewer'||showFields){focusField(section,field);return;}
    pendingFocus.current={section,field}; setDetailsOpen(true);
  };
  useEffect(()=>{if(showFields&&pendingFocus.current){const target=pendingFocus.current;pendingFocus.current=null;focusField(target.section,target.field);}},[showFields]);
  const fieldIssue = (field:string) => fieldTasks.find(task=>task.field===field)?.label;
  const fieldProps = (field:string) => ({'data-review-field':field,'aria-invalid':!!fieldIssue(field)});
  const fieldHint = (field:string) => fieldIssue(field)?<span className="field-required-hint">{fieldIssue(field)}</span>:null;
  const correction = () => `Updated ${Object.keys(spec).filter(key=>JSON.stringify(spec[key as keyof RuleSpec])!==JSON.stringify(candidate?.spec[key as keyof RuleSpec])).map(key=>key.replaceAll('_',' ')).join(', ')} during rule review.`;
  const approve = async () => {
    if(tasks.length){goTo(tasks[0].section,tasks[0].field);return;}
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
    if (spec.standard_check && spec.assertion) throw new Error('Standard checks use catalog parameters. Remove the custom assertion from Technical settings.');
    await onSave(spec,review?correction():note);} catch(e){setError((e as Error).message);} };
  return <div className={review?'guided-rule-review':''}>
    {review&&candidate&&presentation&&<div className={`review-readiness ${dirty?'informational':presentation.kind==='fields'?'needs-input':presentation.kind==='ready'?'ready':'informational'}`} role="status">
      <div><strong>{dirty?'Unsaved changes':presentation.title}</strong><span>{dirty?'Save your changes when ready. You can leave this rule pending.':presentation.detail}</span></div>
      {presentation.kind==='fields'&&<ul>{fieldTasks.map((task,i)=><li key={i}><button className="text-button" onClick={()=>goTo(task.section,task.field)}>{task.label} →</button></li>)}</ul>}
    </div>}
    {review&&candidate&&<ResolutionDetails candidate={candidate} dirty={dirty||advanced!==null} disabled={busy||!review.editable} names={{...operationalCategoryLabels,...Object.fromEntries(consumptionPointOptions),...Object.fromEntries([...(types.data||[]),...(checks.data||[])].map(entry=>[entry.id,entry.label]))}} onUse={value=>{setSpec(value);setDetailsOpen(true);setNote('Applied source-backed proposed corrections.');}}/>}
    {review&&candidate&&candidate.status==='pending'&&!working&&<AssessmentDetails showSummary={false} candidate={candidate} dirty={dirty||advanced!==null} goTo={goTo} onOpenRelated={review.onOpenRelated}/>}
    {review&&candidate?.review?.mode==='automatic_duplicate'&&typeof candidate.review.duplicate_of==='string'&&review.onOpenRelated&&<p><button className="text-button" onClick={()=>review.onOpenRelated?.(String(candidate.review?.duplicate_of))}>View retained rule →</button></p>}
    <div className="rule-review-grid compact-rule-editor"><div className="rule-form">
    {review&&!showFields&&<section className="rule-reading-view">
      <h3>{spec.title}</h3><p className="rule-reading-instruction">{spec.instruction}</p>
      <dl><div><dt>When it applies</dt><dd>{spec.applicability_text}</dd></div>{!!spec.exceptions?.length&&<div><dt>Exceptions</dt><dd><ul>{spec.exceptions.map((item,i)=><li key={i}>{item.description}</li>)}</ul></dd></div>}</dl>
      <RuleUsage spec={spec} status={checkStatus} ruleType={ruleType}/>
      {!!spec.unresolved_questions?.length&&<div className="rule-open-questions"><strong>{working?'Questions being checked':'Unanswered questions'}</strong><ul>{spec.unresolved_questions.map((question,i)=><li key={i}>{question}</li>)}</ul><p>You can leave these unanswered until the source or a policy owner provides an answer.</p></div>}
      {review.editable&&candidate?.status!=='ignored'&&<button type="button" className="secondary" onClick={()=>setDetailsOpen(true)}>Edit rule details</button>}
    </section>}
    {review&&showFields&&<div className="editor-heading"><h3>Edit rule details</h3>{!dirty&&advanced===null&&!fieldTasks.length&&<button className="text-button" onClick={()=>setDetailsOpen(false)}>Close editor</button>}</div>}
    <fieldset hidden={!showFields} className="review-editable-fields" disabled={busy||!!review&&(!review.editable||candidate?.status==='ignored')}>
    <RuleUsage spec={spec} status={checkStatus} ruleType={ruleType} onEditVerification={()=>goTo('verification')} onEditWorkflows={()=>goTo('classification')}/>
    <div ref={el=>{sections.current.instruction=el;}}>
    <div className="editor-heading"><h3>{review?'Instruction':candidate?'Edit rule':'New rule'}</h3><span className="muted">{review?(dirty?'Unsaved changes':'Change only what the source supports'):'Changes need review'}</span></div>
    <label>Title<input {...fieldProps('title')} maxLength={250} value={spec.title} onChange={e=>set('title',e.target.value)}/>{fieldHint('title')}</label>
    <label>Instruction<textarea {...fieldProps('instruction')} rows={3} value={spec.instruction} onChange={e=>set('instruction',e.target.value)}/>{fieldHint('instruction')}</label>

    </div>
    <details ref={el=>{sections.current.classification=el;}} open={review&&initialTasks.current.some(t=>t.section==='classification')} className="editor-section"><summary><span>Where it’s used & rule type</span><small title={classificationSummary}>{classificationSummary}</small></summary><div className="editor-section-body">
      <RuleDeliveryEditor spec={spec} onChange={setSpec} compact={!!review}/>
      {!spec.rule_type&&<>
        <label>Category<select {...fieldProps('operational_category')} value={spec.operational_category||'unclassified'} onChange={e=>set('operational_category',e.target.value as RuleSpec['operational_category'])}>{Object.entries(operationalCategoryLabels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select>{fieldHint('operational_category')}</label>
        <div className="workflow-selection"><span className="field-label">Used in</span><div className="workflow-chips">{workflows.length?workflows.map(([id,label])=><span className="workflow-chip" key={id}>{label}<button type="button" aria-label={`Remove ${label}`} onClick={()=>set('consumption_points',(spec.consumption_points||[]).filter(p=>p!==id))}>×</button></span>):<span className="muted">No workflows assigned</span>}</div>
          <label>Add workflow<select {...fieldProps('consumption_points')} value="" onChange={e=>{if(e.target.value)set('consumption_points',[...(spec.consumption_points||[]),e.target.value as NonNullable<RuleSpec['consumption_points']>[number]]);}}><option value="">Choose a workflow…</option>{consumptionPointOptions.filter(([id])=>!spec.consumption_points?.includes(id as NonNullable<RuleSpec['consumption_points']>[number])).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select>{fieldHint('consumption_points')}</label>
        </div>
      </>}
      <div className="form-row"><label>Rule use<select {...fieldProps('purpose')} disabled={spec.rule_type?.id==='general.guidance'} value={spec.purpose||'unclassified'} onChange={e=>setSpec(s=>({...s,purpose:e.target.value as RuleSpec['purpose'],...(e.target.value!=='shipment_validation'?{execution_mode:'standard' as const}:{}),...(s.schema_version==='1.2'&&!s.standard_check&&!s.rule_type&&e.target.value==='shipment_validation'?{verification:'unresolved',assertion:null}:{})}))}>{Object.entries(rulePurposeLabels).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select>{fieldHint('purpose')}</label>
      <label>Obligation<select value={spec.obligation} onChange={e=>set('obligation',e.target.value as RuleSpec['obligation'])}>{['required','prohibited','recommended','informational'].map(v=><option key={v}>{v}</option>)}</select></label></div>
      <p className="field-hint">Guidance appears in instructions; shipment rules can also be checked.</p>
    </div></details>

    <details ref={el=>{sections.current.conditions=el;}} open={review&&initialTasks.current.some(t=>t.section==='conditions')} className="editor-section"><summary><span>When it applies</span><small>{spec.applicability_text||describeCondition(spec.applicability)}{spec.exceptions?.length?` · ${spec.exceptions.length} exception(s)`:''}</small></summary><div className="editor-section-body">
      <label>Subject<select value={spec.subject} onChange={e=>set('subject',e.target.value as RuleSpec['subject'])}>{['shipment','order','pallet','carton','item','label','document'].map(v=><option key={v}>{v}</option>)}</select></label>
      <ConditionBuilder subject={spec.subject} value={spec.applicability} onChange={value=>{set('applicability',value);set('applicability_text',describeCondition(value));}}/>
      <label>Applies when (description)<textarea {...fieldProps('applicability_text')} rows={2} value={spec.applicability_text} onChange={e=>set('applicability_text',e.target.value)}/>{fieldHint('applicability_text')}</label>
      {spec.exceptions?.map((exception,i)=><p className="field-hint" key={i}><strong>Exception:</strong> {exception.description}</p>)}
      {!!spec.exceptions?.length&&<p className="field-hint">Exception conditions are available under Open questions & additional settings → Technical settings.</p>}
    </div></details>

    <details ref={el=>{sections.current.verification=el;}} open={review&&initialTasks.current.some(t=>t.section==='verification')} className="editor-section"><summary><span>How it’s verified</span><small title={verificationDescription}>{verificationDescription}</small></summary><div className="editor-section-body">
      {spec.rule_type?.id==='general.guidance'&&<p className="field-hint">Reference only. General guidance is displayed as instructions and is excluded from shipment checks.</p>}
      {spec.purpose!=='general_guidance'&&<StandardCheckEditor spec={spec} onChange={setSpec} issues={fieldTasks.filter(task=>task.section==='verification')}/>}
      {spec.rule_type?.id!=='general.guidance'&&!spec.standard_check&&(spec.schema_version!=='1.2'||spec.purpose==='general_guidance')&&<label>Verification method<select value={spec.verification} onChange={e=>set('verification',e.target.value as RuleSpec['verification'])}><option value="data">Automatic data check</option><option value="human">Human inspection</option><option value="external_evidence">External evidence required</option><option value="unresolved">Unresolved interpretation</option></select></label>}
      {spec.verification==='data'&&!spec.standard_check&&spec.schema_version!=='1.2'&&<ConditionBuilder subject={spec.subject} label="Automatic check passes when" value={spec.assertion} onChange={value=>set('assertion',value)}/>}
    </div></details>

    <details ref={el=>{sections.current.evidence=el;}} open={review&&initialTasks.current.some(t=>t.section==='evidence')} className="editor-section"><summary><span>Sources & images</span><small>{spec.evidence.length} reference(s) · PDF page {[...new Set(spec.evidence.map(e=>e.page))].join(', ')}</small></summary><div className="editor-section-body" data-review-field="evidence">
{fieldHint('evidence')}
{review&&!!candidate?.evidence_issues?.length&&<div className="evidence-warning">{candidate.evidence_issues.map((issue,i)=><p key={i}>{issue}</p>)}<small>Corrected references are checked again when you save.</small></div>}
{spec.evidence.map((e,i)=><div className="reference-fields" key={i}><div className="form-row"><label>PDF page<input type="number" min="1" value={e.page} onChange={v=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,page:Number(v.target.value)}:old))}/></label><label>Evidence type<select value={e.kind} onChange={v=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,kind:v.target.value as 'text'|'visual'}:old))}><option value="text">Exact text excerpt</option><option value="visual">Visual evidence</option></select></label></div><label>Excerpt or description<textarea {...fieldProps(`evidence:${i}`)} value={e.quote} onChange={v=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,quote:v.target.value}:old))}/>{fieldHint(`evidence:${i}`)}</label><details><summary>Select diagram / image region</summary><RegionPicker key={`${i}:${e.page}`} guideId={guideId} evidence={e} onChange={region=>set('evidence',spec.evidence.map((old,j)=>j===i?{...old,region}:old))}/></details><button className="text-button" disabled={spec.evidence.length===1} onClick={()=>set('evidence',spec.evidence.filter((_,j)=>j!==i))}>Remove reference</button></div>)}<button className="text-button" onClick={()=>set('evidence',[...spec.evidence,{page:1,quote:'',kind:'text',region:null}])}>Add reference</button>
    </div></details>
    <details ref={el=>{sections.current.advanced=el;}} className="editor-section advanced"><summary><span>Open questions & additional settings</span><small>{advanced!==null?'Unapplied changes':`${spec.unresolved_questions?.length||0} open questions`}</small></summary><div className="editor-section-body">
      <p>Leave a question open if the source does not establish an answer. Remove it only once it has been resolved.</p>
      {spec.unresolved_questions?.map((question,i)=><div className="rule-question-editor" key={i}><label>Question {i+1}<textarea disabled={advanced!==null} rows={2} value={question} onChange={e=>set('unresolved_questions',(spec.unresolved_questions||[]).map((value,j)=>i===j?e.target.value:value))}/></label><button className="text-button" disabled={advanced!==null} onClick={()=>set('unresolved_questions',(spec.unresolved_questions||[]).filter((_,j)=>j!==i))}>Remove resolved question</button></div>)}
      {!spec.unresolved_questions?.length&&<p className="muted">No open questions recorded.</p>}
      <details className="technical-rule-settings"><summary>Technical settings (JSON)</summary><p className="muted">True must mean compliance. Use field paths, explicit measurement units, and the supported expression operators. Leave the assertion null for human checks. Unresolved conditions remain Cannot determine.</p><textarea data-review-field="technical" aria-label="Rule conditions JSON" className="json-editor" rows={15} value={advanced??advancedValue} onChange={e=>changeAdvanced(e.target.value)}/>{advanced!==null&&<><p className="notice">Apply or discard the JSON changes before saving the rule.</p>{advancedError&&<p className="error">{advancedError}</p>}<div className="action-row"><button className="secondary" disabled={!!advancedError} onClick={applyAdvanced}>Apply JSON</button><button className="text-button" onClick={()=>{setAdvanced(null);setAdvancedError('');}}>Discard JSON changes</button></div></>}</details></div></details>

    </fieldset>
    {review&&candidate&&<details className="review-cautions"><summary>Earlier notes & decision history</summary>
      <p className="field-hint">These notes may predate the current checks. Current findings are shown above; older notes do not create additional required fields.</p>
      <ul>{candidate.individual_review_reasons.map((reason,i)=><li key={i}>{reason}</li>)}</ul>
      {!!candidate.evidence_issues?.length&&<ul>{candidate.evidence_issues.map((issue,i)=><li key={i}>{issue}</li>)}</ul>}
      {spec.unresolved_questions?.map((q,i)=><p key={i}>{q}</p>)}
      {candidate.review&&<p>Last decision by {String(candidate.review.actor)}{candidate.review.note?`: ${String(candidate.review.note)}`:''}</p>}
      {!!candidate.classification?.reason&&<p>{String(candidate.classification.reason)}</p>}
      {candidate.carried_from_release_id&&<p>Approval carried forward from the previous release.</p>}
    </details>}
    {!review&&!!spec.unresolved_questions?.length&&<p className="notice">{spec.unresolved_questions.join(' ')}</p>}
    {advanced!==null&&<p className="notice">Apply or discard the technical settings changes before saving.</p>}
    {error&&<div className="error" role="alert">{error}</div>}
    </div><Evidence guideId={guideId} spec={spec} collapsibleImage/></div>
    {review&&candidate?<div className="review-action-dock">
      {review.error&&<div className="error review-submit-error" role="alert"><strong>Could not save this decision</strong><p>{review.error}</p></div>}
      <div hidden={!review.editable||working} className="review-action-identity" ref={el=>{sections.current.reviewer=el;}}>
        <label>Your name for manual decisions<input value={review.actor} onChange={e=>review.onActorChange(e.target.value)} placeholder="Your name" autoComplete="name" disabled={busy}/><small>Saved for all rules in this browser. Only needed when you record a decision.</small></label>
        <span className="review-action-hint">{working?'No action needed while automatic review runs.':!review.editable?'This version is read only.':candidate.status==='ignored'?'Restore this rule before making changes.':dirty?'Save your changes, or discard them.':candidate.status==='approved'?'Approved. No action needed.':fieldTasks.length?fieldTasks.map(task=>task.label).join(' · '):'You can leave this rule pending and return later.'}</span>
      </div>
      {rejecting?<div className="review-rejection-form">
        <label>Reason for rejection<textarea autoFocus rows={2} maxLength={5000} value={note} onChange={e=>setNote(e.target.value)} placeholder="Explain why this proposal should be rejected" disabled={busy} required/></label>
        <div className="review-action-primary"><button className="secondary" disabled={busy} onClick={()=>{setRejecting(false);setNote('');}}>Cancel</button><button className="secondary danger-button" disabled={busy||dirty||advanced!==null||!review.editable||!note.trim()} onClick={()=>review.actor.trim()?review.onDecision('reject',note):goTo('reviewer')}><X size={15}/>{busy?'Saving…':'Reject rule'}</button></div>
      </div>:<div className="review-action-buttons">
        <div hidden={!review.editable||working} className="review-action-secondary" role="group" aria-label="Other rule actions">
        {candidate.status==='ignored'?<button className="secondary" disabled={busy||!review.editable} onClick={()=>review.actor.trim()?review.onDecision('restore',''):goTo('reviewer')}>Restore to review</button>:<>
          <button className="secondary" disabled={busy||dirty||advanced!==null||!review.editable} title={dirty?'Save or discard changes first':'Exclude from publication; you can restore it later'} onClick={()=>review.actor.trim()?review.onDecision('ignore',''):goTo('reviewer')}><EyeOff size={15}/>Ignore</button>
          <button className="secondary danger-button" disabled={busy||dirty||advanced!==null||!review.editable} onClick={()=>setRejecting(true)}><X size={15}/>Reject…</button>
        </>}
        {candidate.status==='approved'&&candidate.review?.mode==='automatic'&&<button className="secondary" disabled={busy||dirty||!review.editable} onClick={()=>review.actor.trim()?review.onDecision('restore','Returned automatic approval to review.'):goTo('reviewer')}>Return to review</button>}
        {review.onVariant&&<button className="secondary" disabled={busy||dirty||advanced!==null||!review.editable} onClick={review.onVariant}><Copy size={15}/>Create variant</button>}
        </div>
        <div className="review-action-primary">
          {dirty||advanced!==null?<><button className="secondary" disabled={busy} onClick={()=>{setSpec(candidate.spec);setAdvanced(null);setError('');setNote('');}}>Discard changes</button><button className="secondary" disabled={busy||advanced!==null||!review.editable} onClick={()=>review.actor.trim()?save():goTo('reviewer')}>Save draft</button></>:<button className="secondary" disabled={busy} onClick={review.onNext||onCancel}>{review.onNext?(candidate.status==='pending'?'Leave for later →':'Next rule →'):'Close rule'}</button>}
          {candidate.status!=='ignored'&&review.editable&&!working&&<button className="primary" disabled={busy||!review.editable||candidate.status==='approved'&&!dirty} onClick={approve}><Check size={15}/>{busy?'Saving…':candidate.status==='approved'&&!dirty?'Approved':fieldTasks.length?fieldTasks[0].label:!review.actor.trim()?'Enter your name to approve':dirty?'Save & approve':candidate.status==='approved'?'Approved':'Approve rule'}</button>}
        </div>
      </div>}
    </div>:<div className="editor-save-bar">

      {candidate&&<label>Reason for change<input value={note} onChange={e=>setNote(e.target.value)} placeholder="Briefly describe your correction" required/></label>}
      {error&&<div className="error" role="alert">{error}</div>}
      <div className="editor-save-actions"><small className="muted">{candidate?'Saving clears prior approval.':'Saved as a draft.'}</small><button className="secondary" onClick={onCancel}>Cancel</button><button className="primary" onClick={save} disabled={busy||advanced!==null||!!candidate&&!note.trim()}>{busy?'Saving…':'Save draft'}</button></div>
    </div>}
  </div>;
}
