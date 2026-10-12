import { useEffect, useState } from 'react';
import { Check, Pencil, Plus, X } from 'lucide-react';
import { jsonRequest, useRemote } from './api';
import type { Candidate, Comparison, RuleSpec, Run } from './api';
import RuleEditor, {Evidence} from './RuleEditor';
import { rulePurposeLabels, shipmentCheckMode } from './rulePurpose';

const ruleTypes: { value: RuleSpec['subject']; label: string }[] = [
  { value: 'shipment', label: 'Shipments' },
  { value: 'order', label: 'Orders' },
  { value: 'pallet', label: 'Pallets' },
  { value: 'carton', label: 'Cartons' },
  { value: 'item', label: 'Items' },
  { value: 'label', label: 'Labels' },
  { value: 'document', label: 'Documents' },
];

export default function ReviewPanel({run,actor,reload}: {run:Run;actor:string;reload:()=>void}) {
  const comparison=useRemote<Comparison>(`/api/analysis/${run.id}/comparison`,0,run.version);
  const [checked,setChecked]=useState<Record<string,number>>({});
  const [bulkNote,setBulkNote]=useState('');
  const [scopeConfirmed,setScopeConfirmed]=useState(false);
  const [message,setMessage]=useState('');
  useEffect(()=>{setChecked({});},[run.version]);
  useEffect(()=>{setScopeConfirmed(false);},[comparison.data?.base_release_id]);
  const [selected,setSelected] = useState('');
  const [filter,setFilter] = useState('pending');
  const [purpose,setPurpose]=useState('all');
  const [checkMode,setCheckMode]=useState('all');
  const classificationJob=run.payload.classification_job;
  const classifying=!!classificationJob&&['queued','running'].includes(String(classificationJob.status));
  const unclassified=run.payload.rules.filter(r=>r.status==='pending'&&(r.spec.purpose||'unclassified')==='unclassified').length;
  const [type,setType] = useState<RuleSpec['subject'] | 'all'>('all');
  const [editing,setEditing] = useState(false);
  const [adding,setAdding] = useState(false);
  const [note,setNote] = useState('');
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [coverageNote,setCoverageNote] = useState('');
  const current = run.payload.rules.find(r=>r.id===selected);
  const editable = run.status==='complete';
  const action = async (url:string, body:unknown, method='POST') => {setBusy(true);setError('');try {await jsonRequest(url,body,method);reload();return true;}catch(e){setError((e as Error).message);return false;}finally{setBusy(false);}};
  const decision = async (candidate:Candidate, kind:'approve'|'reject') => {if(await action(`/api/analysis/${run.id}/rules/${candidate.id}`,{version:run.version,actor,note,action:kind},'PUT'))setNote('');};
  const save = async (spec:RuleSpec,correctionNote:string) => {
    const done=await action(adding?`/api/analysis/${run.id}/rules`:`/api/analysis/${run.id}/rules/${current!.id}`,adding?{version:run.version,actor,spec}:{version:run.version,actor,spec,note:correctionNote,action:'save'},adding?'POST':'PUT');
    if(done){setEditing(false);setAdding(false);}
  };
  const pending=run.payload.rules.filter(r=>r.status==='pending').length;
  const filtered=run.payload.rules.filter(r=>(filter==='all'||(filter==='individual'?r.status==='pending'&&!!r.individual_review_reasons.length:r.status===filter))&&(type==='all'||r.spec.subject===type)&&(purpose==='all'||(r.spec.purpose||'unclassified')===purpose)&&(checkMode==='all'||(r.spec.purpose==='shipment_validation'&&(checkMode==='automatic'?r.spec.verification==='data':r.spec.verification!=='data'))));
  const eligible=filtered.filter(r=>r.status==='pending'&&!r.individual_review_reasons.length);
  const selectedRules=run.payload.rules.filter(r=>checked[r.id]===r.revision);
  const selectedCount=selectedRules.length;
  const selectedFlagged=selectedRules.filter(r=>r.individual_review_reasons.length>0).length;
  const pendingInView=filtered.filter(r=>r.status==='pending');
  const classify=async(nextPurpose:'general_guidance'|'shipment_validation')=>{
    if(await action(`/api/analysis/${run.id}/classify`,{version:run.version,actor,revisions:checked,purpose:nextPurpose})){
      setMessage(`${selectedCount} rules classified as ${rulePurposeLabels[nextPurpose].toLowerCase()}. They remain pending approval.`);
      setChecked({});
    }
  };
  const carryCount=run.payload.rules.filter(r=>r.status==='pending'&&comparison.data?.unchanged?.[r.id]).length;
  const bulkApprove=async()=>{
    if(await action(`/api/analysis/${run.id}/bulk-approve`,{version:run.version,actor,note:bulkNote,revisions:checked})){
      setMessage(`${selectedCount} rules approved. Each approval is recorded against its exact revision.`);
      setChecked({});setBulkNote('');
    }
  };
  const groups=ruleTypes.map(group=>({...group, rules:filtered.filter(r=>r.spec.subject===group.value)})).filter(group=>group.rules.length>0);
  const categories=[{value:'all' as const,label:'All types'},...ruleTypes].map(group=>{
    const rules=run.payload.rules.filter(r=>(group.value==='all'||r.spec.subject===group.value)&&(purpose==='all'||(r.spec.purpose||'unclassified')===purpose));
    return {...group,total:rules.length,pending:rules.filter(r=>r.status==='pending').length};
  });
  return <div className="review-panel"><div className="section-heading"><div><h2>Review the rules</h2><p>{pending} awaiting a decision · {run.payload.rules.length} total proposals</p></div><button className="secondary" disabled={!editable} onClick={()=>{setAdding(true);setEditing(false);}}><Plus size={16}/> Add rule</button></div>
    {message&&<p className="notice" role="status">{message}</p>}
    {error&&<div className="error" role="alert">{error}</div>}
    {comparison.error&&<p className="error">{comparison.error}</p>}
    {comparison.data?.base_release_id&&<div className="update-review-summary"><h3>Changes since {comparison.data.base_name}</h3>
      <p>{Object.keys(comparison.data.unchanged||{}).length} exact matches · {Object.keys(comparison.data.changed||{}).length} possible changes · {(comparison.data.added||[]).length} unmatched proposals · {(comparison.data.missing||[]).length} previous rules missing</p>
      {carryCount>0&&editable&&<><p>Carry forward prior approvals for exact text matches. Current source citations are checked again; changes, exceptions and visual evidence need review.</p><p><strong>Previous scope:</strong> {comparison.data.base_scope}</p>
        <label className="checkbox-label"><input type="checkbox" checked={scopeConfirmed} onChange={e=>setScopeConfirmed(e.target.checked)}/>This guide covers the same operational scope as the previous release.</label>
        <button className="secondary" disabled={busy||!scopeConfirmed||!actor.trim()} onClick={async()=>{if(await action(`/api/analysis/${run.id}/carry-approvals`,{version:run.version,actor,base_release_id:comparison.data!.base_release_id,scope_confirmed:scopeConfirmed})){setMessage(`${carryCount} unchanged approvals carried forward. Review the remaining proposals and missing rules.`);}}}>Carry forward {carryCount} unchanged approvals</button></>}
      <p className="muted">Missing rules need a retain-or-retire decision in Changes & publish. Matching titles are only suggestions.</p>
    </div>}
    {editable&&(unclassified>0||classificationJob)&&<section className="auto-classification"><div className="section-heading"><div><h3>Automatically classify rule use</h3><p>Separate business guidance from shipment requirements using the extracted instructions and source excerpts.</p></div></div>
      {classifying?<><p role="status">Classifying {String(classificationJob!.processed)} of {String(classificationJob!.total)} rules… Completed batches are saved.</p><button className="secondary" disabled={busy} onClick={()=>action(`/api/analysis/${run.id}/cancel-classification`,{version:run.version,actor:actor.trim()||'User'})}>Stop classification</button></>:<>
        {classificationJob?.status==='failed'&&<p className="error" role="alert">{String(classificationJob.error)}</p>}
        {classificationJob?.status==='complete'&&<p className="muted">{String(classificationJob.applied)} rules classified · {String(classificationJob.skipped)} edited or decided rules left untouched.</p>}
        {(unclassified>0||classificationJob?.status==='failed')&&<button className="primary" disabled={busy} onClick={()=>action(`/api/analysis/${run.id}/auto-classify`,{version:run.version,actor:actor.trim()||'User',provider:run.config.provider==='openai'?'openai':'anthropic',model:typeof run.config.model==='string'?run.config.model:''})}>{classificationJob?.status==='failed'?'Resume automatic classification':`Auto-classify ${unclassified} remaining rules`}</button>}
      </>}
      <p className="muted">Uses the analysis provider and model. Sends rule text and excerpts, without rereading the PDF. API charges may apply. Existing classifications, edits and approvals are preserved.</p>
    </section>}
    <details className="coverage"><summary>Page coverage · {run.payload.coverage.length} pages examined · {run.payload.coverage.filter(p=>p.outcome==='needs_review').length} unresolved</summary><p className="muted">Covers and indexes can be marked “No rules” after inspection. Every page remains accounted for.</p><label>Coverage review note<input value={coverageNote} onChange={e=>setCoverageNote(e.target.value)} placeholder="Explain your source inspection"/></label><div className="coverage-list">{run.payload.coverage.map(p=><div key={p.page}><a href={`/api/guides/${run.guide_id}/pages/${p.page-1}/image`} target="_blank" rel="noreferrer">PDF page {p.page}</a><span>{p.outcome.replaceAll('_',' ')} — {p.note}</span>{editable&&<><button disabled={busy} onClick={()=>action(`/api/analysis/${run.id}/coverage`,{version:run.version,actor,note:coverageNote,page:p.page,outcome:'no_rules'},'PUT')}>No rules</button><button disabled={busy} onClick={()=>action(`/api/analysis/${run.id}/coverage`,{version:run.version,actor,note:coverageNote,page:p.page,outcome:'rules_found'},'PUT')}>Rules reviewed</button></>}</div>)}</div></details>
    {run.payload.warnings.length>0&&<details className="coverage"><summary>Analysis notes · {run.payload.warnings.length}</summary><ul>{run.payload.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul></details>}
    {adding||editing&&current ? <RuleEditor key={adding?'new':`${current!.id}:${current!.revision}`} candidate={adding?undefined:current} guideId={run.guide_id} onSave={save} onCancel={()=>{setEditing(false);setAdding(false);}} busy={busy}/> : <>
      <div className="rule-purpose-filters" role="group" aria-label="Rule use">
        {[['all','All uses'],...Object.entries(rulePurposeLabels)].map(([value,label])=><button className={`secondary ${purpose===value?'selected':''}`} key={value} aria-pressed={purpose===value} onClick={()=>{setPurpose(value);setType('all');setCheckMode('all');setChecked({});setSelected('');setNote('');}}>{label} <strong>{run.payload.rules.filter(r=>value==='all'||(r.spec.purpose||'unclassified')===value).length}</strong></button>)}
      </div>
      <p className="muted">General guidance covers onboarding and business instructions. Shipment validation covers checks on individual shipments, including inspections and document evidence. Use automatic classification for older rules, then adjust any categories as needed.</p>
      <div className="rule-type-filters" role="group" aria-label="Rule type">
        {categories.map(category=><button key={category.value} className={`rule-type-filter ${type===category.value?'selected':''}`} aria-pressed={type===category.value} onClick={()=>{setType(category.value);setSelected('');setNote('');setChecked({});}}>
          <span>{category.label}<strong>{category.total}</strong></span>
          <small>{category.pending} awaiting review</small>
        </button>)}
      </div>
      {editable&&<div className="bulk-review-actions">
        <div className="action-row"><button className="secondary" disabled={busy||!pendingInView.length} onClick={()=>setChecked(Object.fromEntries(pendingInView.map(r=>[r.id,r.revision])))}>Select {pendingInView.length} pending {pendingInView.length===1?'rule':'rules'}</button><button className="secondary" disabled={busy||!eligible.length} onClick={()=>setChecked(Object.fromEntries(eligible.map(r=>[r.id,r.revision])))}>Select {eligible.length} eligible {eligible.length===1?'rule':'rules'} in this view</button><button className="text-button" disabled={busy||!selectedCount} onClick={()=>setChecked({})}>Clear selection</button><strong>{selectedCount} selected</strong></div>
        <p className="muted">Read the instructions and source excerpts below. You can classify any selection together. Flagged rules still require individual approval.</p>
        {selectedCount>0&&<><div className="action-row"><button className="secondary" disabled={busy||!actor.trim()} onClick={()=>classify('general_guidance')}>Classify as general guidance</button><button className="secondary" disabled={busy||!actor.trim()} onClick={()=>classify('shipment_validation')}>Classify as shipment validation</button></div><p className="muted">Classification records the intended use; it does not approve the rules.</p><label>Batch note (optional)<input value={bulkNote} onChange={e=>setBulkNote(e.target.value)} placeholder="Only if there is additional context"/></label><button className="primary" disabled={busy||!actor.trim()||selectedFlagged>0} onClick={bulkApprove}><Check size={16}/>Approve {selectedCount} selected rules</button>{selectedFlagged>0&&<p className="muted">{selectedFlagged} selected rules need classification or individual review before approval.</p>}{!actor.trim()&&<p className="muted">Enter your reviewer name above to classify or approve.</p>}</>}
      </div>}
      <div className={`review-layout bulk-review-layout ${current?'has-selection':''}`}><div className="rule-list" key={`${type}:${filter}:${purpose}:${checkMode}`}>

        <label htmlFor="review-filter">Review status<select id="review-filter" value={filter} onChange={e=>{setFilter(e.target.value);setSelected('');setNote('');setChecked({});}}><option value="pending">Awaiting review</option><option value="individual">Needs individual review</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="all">All proposals</option></select></label>
        <label>Shipment check method<select value={checkMode} onChange={e=>{setCheckMode(e.target.value);if(e.target.value!=='all')setPurpose('shipment_validation');setChecked({});setSelected('');setNote('');}}><option value="all">All uses and methods</option><option value="automatic">Automatic shipment checks only</option><option value="manual">Shipment inspection / evidence only</option></select></label>
        <p className="rule-list-count" role="status">{filtered.length} {filtered.length===1?'proposal':'proposals'} · {categories.find(category=>category.value===type)?.label}</p>
        {groups.map(group=><section className="rule-type-group" key={group.value} aria-label={group.label}>
          <h3>{group.label}<span>{group.rules.length}</span></h3>
          {group.rules.map(r=><article className={`review-rule-card ${selected===r.id?'selected':''}`} key={r.id}>
            <div className="review-card-heading">{editable&&r.status==='pending'&&<input className="rule-select" type="checkbox" aria-label={`Select ${r.spec.title}`} disabled={busy} checked={checked[r.id]===r.revision} onChange={e=>setChecked(previous=>{const next={...previous};if(e.target.checked)next[r.id]=r.revision;else delete next[r.id];return next;})}/>}
              <button className="text-button" onClick={()=>{setSelected(r.id);setNote('');}}>{r.spec.title}</button><span className={`status-badge ${r.status}`}>{r.status}</span></div>
            <span className={`rule-purpose-badge ${r.spec.purpose||'unclassified'}`}>{rulePurposeLabels[r.spec.purpose||'unclassified']}</span>
            <p>{r.spec.instruction}</p>{!!r.classification?.reason&&<p className="classification-reason">{r.classification.method==='ai'?'AI classification:':'Classification:'} {String(r.classification.reason)}</p>}<p className="muted"><strong>Applies:</strong> {r.spec.applicability_text}</p>
            {r.spec.assertion&&<details className="advanced"><summary>Automatic check</summary><pre>{JSON.stringify(r.spec.assertion,null,2)}</pre></details>}
            <small>{r.spec.obligation} · {shipmentCheckMode(r.spec)}</small>
            {r.individual_review_reasons.length>0&&<div className="review-card-flags"><strong>Individual review required</strong><ul>{r.individual_review_reasons.map((reason,i)=><li key={i}>{reason}</li>)}</ul></div>}
            {r.carried_from_release_id&&<p className="muted">Approval carried forward from the previous release.</p>}
            <div className="review-source-excerpts">{r.spec.evidence.map((e,i)=><blockquote key={i}><a href={`/api/guides/${r.source_guide_id}/pages/${e.page-1}/image`} target="_blank" rel="noreferrer">PDF page {e.page}</a><span>{e.quote}</span></blockquote>)}</div>
            <button className="text-button" onClick={()=>{setSelected(r.id);setNote('');}}>Open full review & source</button>
          </article>)}
        </section>)}
        {!filtered.length&&<p className="muted">No proposals match these filters. {run.payload.rules.length===0?'Add a rule from the source, or start an AI analysis.':'Choose another type or review status.'}</p>}
      </div>
      {current?<div className="rule-review-grid"><article className="rule-interpretation"><div className="action-row"><button className="text-button" onClick={()=>{setSelected('');setNote('');}}>Close detail</button><span className={`status-badge ${current.status}`}>{current.status}</span><button className="text-button" disabled={!editable} onClick={()=>setEditing(true)}><Pencil size={14}/> Edit</button></div><h3>{current.spec.title}</h3>{!!current.evidence_issues?.length&&<div className="evidence-warning" role="status"><strong>Source evidence needs review</strong><ul>{current.evidence_issues.map((issue,i)=><li key={i}>{issue}</li>)}</ul><p>This draft cannot be approved until its source references are corrected. You can also reject it.</p></div>}<p className="instruction">{current.spec.instruction}</p><dl><dt>Rule use</dt><dd>{rulePurposeLabels[current.spec.purpose||'unclassified']}{current.spec.purpose==='general_guidance'&&' — excluded from shipment checks'}</dd><dt>Applies when</dt><dd>{current.spec.applicability_text}</dd><dt>Obligation</dt><dd>{current.spec.obligation}</dd><dt>Shipment check</dt><dd>{shipmentCheckMode(current.spec)}</dd><dt>Verification</dt><dd>{current.spec.verification.replaceAll('_',' ')}</dd></dl>{(current.spec.exceptions || []).map((e,i)=><p key={i}><strong>Exception:</strong> {e.description}</p>)}{(current.spec.unresolved_questions || []).map((q,i)=><p className="error" key={i}>{q}</p>)}{current.spec.assertion&&<details className="advanced"><summary>Automatic check</summary><pre>{JSON.stringify(current.spec.assertion,null,2)}</pre></details>}{current.review&&<p className="review-note">Reviewed by {String(current.review.actor)}{current.review.note?`: ${String(current.review.note)}`:''}</p>}{editable&&<><label>Decision note {current.individual_review_reasons.length?'(required for this rule)':'(optional for approval; required for rejection)'}<textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="Explain exceptions, ambiguity, visual checks or a rejection"/></label><div className="action-row"><button className="secondary" disabled={busy||!note.trim()||!actor.trim()} onClick={()=>decision(current,'reject')}><X size={15}/> Reject</button><button className="primary" disabled={busy||(current.spec.purpose||'unclassified')==='unclassified'||!!current.individual_review_reasons.length&&!note.trim()||!actor.trim()||!!current.evidence_issues?.length} onClick={()=>decision(current,'approve')}><Check size={15}/> Approve revision</button></div></>}</article><Evidence guideId={current.source_guide_id} spec={current.spec}/></div>:null}
    </div></>}
  </div>;
}
