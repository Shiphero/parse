import { Fragment, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Plus, Search, SlidersHorizontal } from 'lucide-react';
import { jsonRequest, useRemote } from './api';
import type { Candidate, Comparison, Connection, RuleSpec, Run, RuleTypeDefinition } from './api';
import RuleEditor from './RuleEditor';
import CategorizeRulesDialog from './CategorizeRulesDialog';
import { activeWorkflows, operationalCategoryLabels, consumptionPointOptions, needsClassification } from './ruleTaxonomy';
import { rulePurposeLabels, verificationSummary } from './rulePurpose';
import { VerificationBadge, WorkflowUsage } from './RuleUsage';

const ruleTypes: { value: RuleSpec['subject']; label: string }[] = [
  { value: 'shipment', label: 'Shipments' }, { value: 'order', label: 'Orders' },
  { value: 'pallet', label: 'Pallets' }, { value: 'carton', label: 'Cartons' },
  { value: 'item', label: 'Items' }, { value: 'label', label: 'Labels' },
  { value: 'document', label: 'Documents' },
];

export default function ReviewPanel({ run, actor, onActorChange, reload, connections, onEditingChange }: {
  run: Run; actor: string; onActorChange: (value: string) => void; reload: () => void; connections: Connection[]; onEditingChange?: (editing:boolean)=>void;
}) {
  const typeCatalog = useRemote<RuleTypeDefinition[]>('/api/rule-types');
  const comparison = useRemote<Comparison>(`/api/analysis/${run.id}/comparison`, 0, run.version);
  const [checked, setChecked] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState('');
  const [filter, setFilter] = useState(run.status === 'published' || run.config.source_release_id ? 'all' : 'pending');
  const [operationalCategory, setOperationalCategory] = useState('all');
  const [consumptionPoint, setConsumptionPoint] = useState('all');
  const [purpose, setPurpose] = useState('all');
  const [standardType,setStandardType]=useState('all');
  const [checkMode, setCheckMode] = useState('all');
  const [type, setType] = useState<RuleSpec['subject'] | 'all'>('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const tableHeading = useRef<HTMLTableElement>(null);
  const pageCheckbox = useRef<HTMLInputElement>(null);
  const [moreFilters, setMoreFilters] = useState(false);
  const [detailedColumns, setDetailedColumns] = useState(false);
  const [bulkOptions, setBulkOptions] = useState(false);
  const [categorizing, setCategorizing] = useState<{ rules: Candidate[]; version: number } | null>(null);
  const [bulkNote, setBulkNote] = useState('');
  const [scopeConfirmed, setScopeConfirmed] = useState(false);
  const [message, setMessage] = useState('');
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [initialRule, setInitialRule] = useState<RuleSpec|undefined>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [coverageNote, setCoverageNote] = useState('');
  const focusAfterNavigation = useRef<{afterVersion:number}|null>(null);
  const activeHeading = useRef<HTMLButtonElement>(null);
  const activeRow = useRef<HTMLTableRowElement>(null);
  const editable = run.status === 'complete';
  const current = run.payload.rules.find(r => r.id === selected);
  const classificationJob = run.payload.classification_job;
  const [classificationProvider,setClassificationProvider] = useState(String(classificationJob?.provider || (run.config.provider==='openai'?'openai':'anthropic')));
  const classificationConnection = connections.find(c=>c.id===classificationProvider);
  const defaultClassificationModel = classificationJob?.provider===classificationProvider
    ? String(classificationJob.model||'') : classificationConnection?.model || (run.config.provider===classificationProvider?String(run.config.model||''):'');
  const [classificationModel,setClassificationModel] = useState(defaultClassificationModel);
  useEffect(()=>{setClassificationModel(defaultClassificationModel);},[classificationProvider,defaultClassificationModel]);
  const classificationConfigured = !!classificationConnection?.credential_configured && !!classificationModel.trim();
  const resumingClassification = classificationJob?.status==='failed' && classificationJob.provider===classificationProvider && classificationJob.model===classificationModel.trim();
  const classifying = !!classificationJob && ['queued', 'running'].includes(String(classificationJob.status));
  const unclassified = run.payload.rules.filter(r => ['pending','approved'].includes(r.status) && (needsClassification(r.spec)||!r.spec.rule_type)).length;
  const untyped = run.payload.rules.filter(r => ['pending','approved'].includes(r.status) && !r.spec.rule_type).length;
  const autoClassify = () => action(`/api/analysis/${run.id}/auto-classify`,{version:run.version,actor:actor.trim()||'User',provider:classificationProvider,model:classificationModel.trim(),include_approved:true});
  const pending = run.payload.rules.filter(r => r.status === 'pending').length;
  const carryCount = run.payload.rules.filter(r => r.status === 'pending' && comparison.data?.unchanged?.[r.id]).length;

  // Polling must not discard the user's selection. A changed revision does need a fresh selection.
  useEffect(() => {
    setChecked(previous => Object.fromEntries(Object.entries(previous).filter(([id, revision]) =>
      run.payload.rules.some(r => r.id === id && r.revision === revision && r.status === 'pending'))));
  }, [run.version]);
  useEffect(() => { setScopeConfirmed(false); }, [comparison.data?.base_release_id]);
  useEffect(() => { onEditingChange?.(editing || adding); return () => onEditingChange?.(false); }, [editing, adding, onEditingChange]);
  const resetView = () => { focusAfterNavigation.current=null; setPage(0); setSelected(''); setChecked({}); setError(''); };
  const resetFilters = () => {
    resetView(); setSearch(''); setOperationalCategory('all'); setConsumptionPoint('all');
    setFilter(run.status === 'published' || run.config.source_release_id ? 'all' : 'pending'); setType('all'); setPurpose('all'); setCheckMode('all'); setStandardType('all');
  };
  const query = search.trim().toLowerCase();
  const filtered = run.payload.rules.filter(r =>
    (standardType==='all'||(standardType==='unmapped'?!r.spec.rule_type:r.spec.rule_type?.id===standardType)) &&
    (operationalCategory === 'all' || (operationalCategory === 'unclassified' ? needsClassification(r.spec) : r.spec.operational_category === operationalCategory)) &&
    (consumptionPoint === 'all' || (consumptionPoint === 'unassigned' ? !activeWorkflows(r.spec).length : activeWorkflows(r.spec).some(p => p === consumptionPoint))) &&
    (filter === 'all' || (filter === 'individual' ? r.status === 'pending' && !!r.individual_review_reasons.length : r.status === filter)) &&
    (type === 'all' || r.spec.subject === type) &&
    (purpose === 'all' || (r.spec.purpose || 'unclassified') === purpose) &&
    (checkMode === 'all' || verificationSummary(r.spec,r.check_status).kind === checkMode) &&
    (!query || [r.spec.title, r.spec.instruction, r.spec.applicability_text, ...r.spec.evidence.map(e => e.quote)].join(' ').toLowerCase().includes(query)));
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount - 1);
  const visibleRules = filtered.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  useLayoutEffect(() => {
    const navigation=focusAfterNavigation.current;
    if (!navigation || run.version<navigation.afterVersion) return;
    // Approval can remove a row from this filter and move the next rule to another page.
    // Align only after the refreshed list and its expanded row have been rendered.
    const index=filtered.findIndex(rule=>rule.id===selected);
    if (index>=0 && Math.floor(index/pageSize)!==currentPage) {
      setPage(Math.floor(index/pageSize));
      return;
    }
    activeHeading.current?.focus({preventScroll:true});
    (activeRow.current||tableHeading.current)?.scrollIntoView({block:'start',inline:'nearest',behavior:'instant'});
    focusAfterNavigation.current=null;
  }, [selected,run.version,currentPage,pageSize]);
  const pagePending = visibleRules.filter(r => r.status === 'pending');
  const pageSelectedCount = pagePending.filter(r => checked[r.id] === r.revision).length;
  useEffect(() => {
    if (pageCheckbox.current) pageCheckbox.current.indeterminate = pageSelectedCount > 0 && pageSelectedCount < pagePending.length;
  }, [pageSelectedCount, pagePending.length]);
  const changePage = (next: number) => {
    focusAfterNavigation.current=null;
    setPage(next); setSelected(''); setError('');
    tableHeading.current?.scrollIntoView({ block: 'start' });
  };
  const eligible = filtered.filter(r => r.status === 'pending' && !r.individual_review_reasons.length && !needsClassification(r.spec) && !r.evidence_issues?.length);
  const pendingInView = filtered.filter(r => r.status === 'pending');
  const selectedRules = run.payload.rules.filter(r => checked[r.id] === r.revision && r.status === 'pending');
  const selectedCount = selectedRules.length;
  const selectedFlagged = selectedRules.filter(r => r.individual_review_reasons.length || needsClassification(r.spec) || r.evidence_issues?.length).length;
  const extraFilterCount = [type, purpose, operationalCategory, standardType].filter(v => v !== 'all').length;
  const selectRules = (rules: Candidate[]) => setChecked(Object.fromEntries(rules.map(r => [r.id, r.revision])));
  const openRule = (id: string, focus = false, afterVersion = run.version) => {
    focusAfterNavigation.current = focus?{afterVersion}:null;
    const index = filtered.findIndex(r => r.id === id);
    if (index >= 0) setPage(Math.floor(index / pageSize));
    setSelected(id); setError('');
  };
  const action = async (url: string, body: unknown, method = 'POST') => {
    setBusy(true); setError('');
    try { await jsonRequest(url, body, method); reload(); return true; }
    catch (e) { setError((e as Error).message); return false; }
    finally { setBusy(false); }
  };
  const decision = async (candidate: Candidate, kind: 'approve' | 'reject' | 'ignore' | 'restore', decisionNote = '') => {
    const index = filtered.findIndex(r => r.id === candidate.id);
    const next = [...filtered.slice(index + 1), ...filtered.slice(0, index)].find(r => r.status === 'pending');
    if (await action(`/api/analysis/${run.id}/rules/${candidate.id}`, { version: run.version, actor, note:decisionNote, action: kind }, 'PUT')) {
      setMessage(`“${candidate.spec.title}” ${{approve:'approved',reject:'rejected',ignore:'ignored. Excluded from publication; restore it using Status → Ignored',restore:'restored to review'}[kind]}.`);
      setChecked(previous => { const updated = { ...previous }; delete updated[candidate.id]; return updated; });
      openRule(next?.id || '', true, run.version+1);
    }
  };
  const save = async (spec: RuleSpec, correctionNote: string) => {
    const done = await action(adding ? `/api/analysis/${run.id}/rules` : `/api/analysis/${run.id}/rules/${current!.id}`,
      adding ? { version: run.version, actor, spec } : { version: run.version, actor, spec, note: correctionNote, action: 'save' }, adding ? 'POST' : 'PUT');
    if (done) { setEditing(false); setAdding(false); setMessage('Draft saved. Approval required.'); }
  };
  const bulkApprove = async () => {
    if (await action(`/api/analysis/${run.id}/bulk-approve`, { version: run.version, actor, note: bulkNote, revisions: checked })) {
      setMessage(`${selectedCount} rules approved.`);
      setChecked({}); setBulkNote(''); setBulkOptions(false);
    }
  };
  const reviewerInput = <label className="reviewer-field">Reviewer name<input value={actor} onChange={e => onActorChange(e.target.value)} placeholder="Your name" autoComplete="name" disabled={busy}/></label>;

  return <div className="review-panel review-workspace">
    <div className="section-heading"><div><h2>Rules</h2><p>{pending} pending · {run.payload.rules.length - pending} decided · {run.payload.rules.length} total</p></div>
      <div className="review-heading-actions"><button className="secondary" aria-pressed={detailedColumns} onClick={() => setDetailedColumns(v => !v)}>{detailedColumns ? 'Fewer columns' : 'More columns'}</button>{editable && <button className="secondary" disabled={busy || editing || adding} onClick={() => { setInitialRule(undefined); setAdding(true); }}><Plus size={16}/> Add rule</button>}</div></div>
    {editable && !!run.config.source_release_id && <p className="notice">Draft of {String(run.config.source_release_name)}.</p>}
    {message && <p className="notice" role="status">{message}</p>}
    {error && !current && !selectedCount && <div className="error" role="alert">{error}</div>}
    {comparison.error && <p className="error">{comparison.error}</p>}
    <details className="review-tools"><summary>Coverage & tools <span>{carryCount > 0 ? ` · ${carryCount} prior approvals available` : ''}</span></summary>
      {reviewerInput}
    {comparison.data?.base_release_id&&<div className="update-review-summary"><h3>Changes since {comparison.data.base_name}</h3>
      <p>{Object.keys(comparison.data.unchanged||{}).length} exact matches · {Object.keys(comparison.data.changed||{}).length} possible changes · {(comparison.data.added||[]).length} unmatched proposals · {(comparison.data.missing||[]).length} previous rules missing</p>
      {carryCount>0&&editable&&<><p>Carry forward prior approvals for exact text matches. Current source citations are checked again; changes, exceptions and visual evidence need review.</p><p><strong>Previous scope:</strong> {comparison.data.base_scope}</p>
        <label className="checkbox-label"><input type="checkbox" checked={scopeConfirmed} onChange={e=>setScopeConfirmed(e.target.checked)}/>This guide covers the same operational scope as the previous release.</label>
        <button className="secondary" disabled={busy||!scopeConfirmed||!actor.trim()} onClick={async()=>{if(await action(`/api/analysis/${run.id}/carry-approvals`,{version:run.version,actor,base_release_id:comparison.data!.base_release_id,scope_confirmed:scopeConfirmed})){setMessage(`${carryCount} unchanged approvals carried forward. Review the remaining proposals and missing rules.`);}}}>Carry forward {carryCount} unchanged approvals</button></>}
      <p className="muted">Decide whether to retain or retire missing rules in Releases.</p>
    </div>}
    {editable&&(unclassified>0||classificationJob)&&<section className="auto-classification"><div className="section-heading"><div><h3>Automatically classify rules</h3><p>Assign rule types and workflow placements. Unmatched requirements stay unmapped.</p></div></div>
      {classifying?<><p role="status">Classifying {String(classificationJob!.processed)} of {String(classificationJob!.total)} rules… Completed batches are saved.</p><button className="secondary" disabled={busy} onClick={()=>action(`/api/analysis/${run.id}/cancel-classification`,{version:run.version,actor:actor.trim()||'User'})}>Stop classification</button></>:<>
        {classificationJob?.status==='failed'&&<p className="error" role="alert">{String(classificationJob.error)}</p>}
        {classificationJob?.status==='complete'&&<p className="muted">{String(classificationJob.applied)} rules classified · {String(classificationJob.skipped)} edited or decided rules left untouched.</p>}
        {(unclassified>0||classificationJob?.status==='failed')&&<button className="primary" disabled={busy||editing||!classificationConfigured} onClick={autoClassify}>{resumingClassification?'Resume automatic classification':`Auto-classify ${unclassified} remaining rules`}</button>}
      </>}
      <p className="muted">Sends rule text and excerpts to the selected provider; API charges apply. Changes to approved rules require review.</p>
    </section>}
    <details className="coverage"><summary>Page coverage · {run.payload.coverage.length} pages examined · {run.payload.coverage.filter(p=>p.outcome==='needs_review').length} unresolved</summary><p className="muted">Covers and indexes can be marked “No rules” after inspection. Every page remains accounted for.</p><label>Coverage review note<input value={coverageNote} onChange={e=>setCoverageNote(e.target.value)} placeholder="Explain your source inspection"/></label><div className="coverage-list">{run.payload.coverage.map(p=><div key={p.page}><a href={`/api/guides/${run.guide_id}/pages/${p.page-1}/image`} target="_blank" rel="noreferrer">PDF page {p.page}</a><span>{p.outcome.replaceAll('_',' ')} — {p.note}</span>{editable&&<><button disabled={busy} onClick={()=>action(`/api/analysis/${run.id}/coverage`,{version:run.version,actor,note:coverageNote,page:p.page,outcome:'no_rules'},'PUT')}>No rules</button><button disabled={busy} onClick={()=>action(`/api/analysis/${run.id}/coverage`,{version:run.version,actor,note:coverageNote,page:p.page,outcome:'rules_found'},'PUT')}>Rules reviewed</button></>}</div>)}</div></details>
    {run.payload.warnings.length>0&&<details className="coverage"><summary>Analysis notes · {run.payload.warnings.length}</summary><ul>{run.payload.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul></details>}
    </details>
    {editable&&!adding&&(unclassified>0||classifying||classificationJob?.status==='failed')&&<div className="rule-type-classification-bar"><span role="status">{classifying?`Classifying ${String(classificationJob!.processed)} of ${String(classificationJob!.total)} rules…`:`${unclassified} rules need classification · ${untyped} need a standard type`}</span>
      <label>Classification provider<select value={classificationProvider} disabled={busy||editing||classifying} onChange={e=>setClassificationProvider(e.target.value)}><option value="anthropic">Claude / Anthropic</option><option value="openai">OpenAI</option><option value="jev">Jev / TypeSafe</option></select></label>
      <label>Model<input value={classificationModel} disabled={busy||editing||classifying} onChange={e=>setClassificationModel(e.target.value)} placeholder="Model ID"/></label>
      <button className="secondary" disabled={busy||editing||classifying||!classificationConfigured} onClick={autoClassify}>{classifying?'Classification running…':resumingClassification?'Resume classification':'Auto-classify rules'}</button><small>Changed approved rules return to review. Sends rule text and excerpts to the selected provider.</small>
      {!classificationConfigured&&<p className="muted">Add an API key and model in Connections to use this provider.</p>}
      {classificationJob?.status==='failed'&&<p className="error" role="alert">{String(classificationJob.error)}</p>}</div>}
    {adding ? <>{initialRule&&<p className="notice">This is a separate draft copied from an existing rule. Adjust its conditions, instruction and image. The original remains unchanged. Check that variant ranges do not overlap and explicitly decide how boundaries such as exactly 7 inches should be handled.</p>}{reviewerInput}{error && <div className="error" role="alert">{error}</div>}<RuleEditor initial={initialRule} guideId={run.guide_id} onSave={save} onCancel={() => setAdding(false)} busy={busy}/></> : <>
      <fieldset className="review-filter-controls" disabled={editing || busy}>
        <legend className="visually-hidden">Filter rules</legend>
        <div className="review-filter-row">
          <label className="review-search"><span>Search rules</span><div><Search size={16} aria-hidden="true"/><input type="search" value={search} onChange={e => { resetView(); setSearch(e.target.value); }} placeholder="Search instructions or source text"/></div></label>
          <label>Verification<select value={checkMode} onChange={e => { resetView(); setCheckMode(e.target.value); }}><option value="all">All methods</option><option value="automatic">Automatic verification</option><option value="manual">Manual verification</option><option value="external">External confirmation</option><option value="unresolved">Not configured / classified</option><option value="guidance">Guidance only</option></select></label>
          <label>Where it’s used<select value={consumptionPoint} onChange={e => { resetView(); setConsumptionPoint(e.target.value); }}><option value="all">All workflows</option><option value="unassigned">No active workflow</option>{consumptionPointOptions.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label>Status<select value={filter} onChange={e => { resetView(); setFilter(e.target.value); }}><option value="pending">Awaiting review</option><option value="individual">Needs individual review</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="ignored">Ignored</option><option value="all">All statuses</option></select></label>
          <button className="secondary" aria-expanded={moreFilters} aria-controls="review-extra-filters" onClick={() => setMoreFilters(!moreFilters)}><SlidersHorizontal size={15}/> Filters{extraFilterCount ? ` (${extraFilterCount})` : ''}</button>
        </div>
        {moreFilters && <div className="review-extra-filters" id="review-extra-filters">
          <label>Subject<select value={type} onChange={e => { resetView(); setType(e.target.value as typeof type); }}><option value="all">All subjects</option>{ruleTypes.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}</select></label>
          <label>Rule use<select value={purpose} onChange={e => { resetView(); setPurpose(e.target.value); setCheckMode('all'); setStandardType('all'); }}><option value="all">All uses</option>{Object.entries(rulePurposeLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          <label>Standard rule type<select value={standardType} onChange={e=>{resetView();setStandardType(e.target.value);}}><option value="all">All standard types</option><option value="unmapped">Needs rule type mapping</option>{typeCatalog.data?.map(t=><option key={t.id} value={t.id}>{t.label}</option>)}</select></label>
          <label>Category<select value={operationalCategory} onChange={e => { resetView(); setOperationalCategory(e.target.value); }}>{[['all', 'All categories'], ...Object.entries(operationalCategoryLabels)].map(([value, label]) => <option key={value} value={value}>{label} ({run.payload.rules.filter(r => value === 'all' || (value === 'unclassified' ? needsClassification(r.spec) : r.spec.operational_category === value)).length})</option>)}</select></label>
          <button className="text-button" onClick={resetFilters}>Reset filters</button>
        </div>}
      </fieldset>
      {operationalCategory === 'unclassified' && <p className="muted compact-review-hint">Missing category, workflow or rule use. Select a rule → <strong>Categorize</strong>.</p>}
      <div className="review-list-toolbar"><span role="status">{filtered.length} {filtered.length === 1 ? 'rule' : 'rules'} shown</span>
        {editable && <div><button className="text-button" disabled={busy || editing || !eligible.length} onClick={() => selectRules(eligible)}>Select {eligible.length} ready to approve</button>
          <button className="text-button" disabled={busy || editing || !pendingInView.length} onClick={() => selectRules(pendingInView)}>Select all pending</button></div>}</div>
      <div className="review-table-scroll" role="region" aria-label="Review rules table" tabIndex={0}>
        <table className={`review-table ${detailedColumns ? '' : 'review-table-compact'}`} ref={tableHeading}>
          <caption className="visually-hidden">Rules with verification, workflow, source page and review status. Open a rule for instructions and evidence.</caption>
          <colgroup><col className="selection-column"/><col className="title-column"/><col className="check-column"/><col className="consumer-column"/>{detailedColumns && <><col className="category-column"/><col className="use-column"/></>}<col className="source-column"/><col className="status-column"/></colgroup>
          <thead><tr><th scope="col">{editable ? <input ref={pageCheckbox} type="checkbox" aria-label="Select pending rules on this page" disabled={busy || editing || !pagePending.length} checked={pagePending.length > 0 && pageSelectedCount === pagePending.length} onChange={e => setChecked(previous => { const next = { ...previous }; pagePending.forEach(r => { if (e.target.checked) next[r.id] = r.revision; else delete next[r.id]; }); return next; })}/> : <span className="visually-hidden">Selection</span>}</th><th scope="col">Rule</th><th scope="col">Verification</th><th scope="col">Where it’s used</th>{detailedColumns && <><th scope="col">Category</th><th scope="col">Use</th></>}<th scope="col">Page</th><th scope="col">Status</th></tr></thead>
          <tbody>
        {visibleRules.map(r => {
          const expanded = selected === r.id;
          const next = filtered.slice(filtered.indexOf(r) + 1).find(candidate => candidate.status === 'pending');
          const standardTypeLabel = typeCatalog.data?.find(t=>t.id===r.spec.rule_type?.id&&t.version===r.spec.rule_type.version)?.label || r.spec.rule_type?.id || 'Type not assigned';

          const pages = [...new Set(r.spec.evidence.map(e => e.page))].join(', ') || '—';
          return <Fragment key={r.id}>
            <tr ref={expanded?activeRow:undefined} className={`review-table-row ${expanded ? 'expanded' : ''} ${checked[r.id] === r.revision ? 'checked' : ''}`}>
              <td>{editable && r.status === 'pending' && <input type="checkbox" aria-label={`Select ${r.spec.title}`} disabled={busy || editing} checked={checked[r.id] === r.revision} onChange={e => setChecked(previous => { const next = { ...previous }; if (e.target.checked) next[r.id] = r.revision; else delete next[r.id]; return next; })}/>}</td>
              <th scope="row"><button className="review-table-title" ref={expanded ? activeHeading : undefined} title={r.spec.title} aria-expanded={expanded} aria-controls={expanded ? `rule-detail-${r.id}` : undefined} disabled={busy || editing} onClick={() => openRule(expanded ? '' : r.id)}>{expanded ? <ChevronUp size={14}/> : <ChevronDown size={14}/>}<span>{r.spec.title}</span></button><span className={`review-rule-type ${r.spec.rule_type?'':'unmapped'}`}>{standardTypeLabel}</span></th>
              <td><VerificationBadge spec={r.spec} status={r.check_status} compact/></td>
              <td><WorkflowUsage spec={r.spec}/></td>
              {detailedColumns && <><td><span className="table-cell-text" title={operationalCategoryLabels[r.spec.operational_category || 'unclassified']}>{operationalCategoryLabels[r.spec.operational_category || 'unclassified']}</span></td>
              <td><span className="table-cell-text" title={rulePurposeLabels[r.spec.purpose || 'unclassified']}>{r.spec.purpose === 'general_guidance' ? 'Guidance' : r.spec.purpose === 'shipment_validation' ? 'Shipment check' : 'Unclassified'}</span></td></>}
              <td><span className="table-cell-text" title={`PDF pages ${pages}`}>{pages}</span></td>
              <td><span className={`status-badge ${r.status} ${r.status === 'pending' && r.individual_review_reasons.length ? 'flagged' : ''}`} title={r.individual_review_reasons.join('; ')}>{r.status === 'pending' ? r.individual_review_reasons.length ? 'Flagged' : 'Pending' : r.status}</span></td>
            </tr>
            {expanded && <tr className="review-detail-row"><td colSpan={detailedColumns ? 8 : 6}><div className="review-inline-detail" id={`rule-detail-${r.id}`}>
              <RuleEditor key={`${r.id}:${r.revision}`} candidate={r} guideId={r.source_guide_id} onSave={save} onCancel={()=>openRule('')} busy={busy}
                review={{actor,onActorChange,editable,error,onDirtyChange:setEditing,
                  onDecision:(kind,note)=>decision(r,kind,note),
                  onNext:next?()=>openRule(next.id,true):undefined,
                  onVariant:r.source_guide_id===run.guide_id?()=>{setInitialRule({...structuredClone(r.spec),title:`${r.spec.title.slice(0,230)} — variant`});setAdding(true);setSelected('');}:undefined,
                  onApprove:async(spec,note,changed)=>{
                    if(!changed){await decision(r,'approve',note);return;}
                    if(await action(`/api/analysis/${run.id}/rules/${r.id}`,{version:run.version,actor,note,action:'save_and_approve',spec},'PUT')){
                      setEditing(false);setMessage(`“${spec.title}” saved and approved.`);openRule(next?.id||'',true,run.version+1);
                    }
                  },
                }}/>
            </div></td></tr>}
          </Fragment>;
        })}
        {!filtered.length && <tr><td colSpan={detailedColumns ? 8 : 6}><div className="review-empty"><Check size={24}/><h3>{pending === 0 && filter === 'pending' && run.payload.rules.length ? 'All rules have a decision' : 'No matching rules'}</h3><p>{run.payload.rules.length ? 'Adjust the filters to see other rules.' : 'Rules will appear here as the guide is analyzed.'}</p><button className="secondary" onClick={resetFilters}>Reset filters</button></div></td></tr>}
          </tbody>
        </table>
      </div>
      <div className="review-pagination"><span>{filtered.length ? currentPage * pageSize + 1 : 0}–{Math.min((currentPage + 1) * pageSize, filtered.length)} of {filtered.length}</span><label>Rows<select aria-label="Rules per page" value={pageSize} disabled={editing || busy} onChange={e => { setPageSize(Number(e.target.value)); changePage(0); }}><option value={25}>25</option><option value={50}>50</option><option value={100}>100</option></select></label><button className="icon-button" aria-label="Previous rules page" disabled={editing || busy || currentPage === 0} onClick={() => changePage(currentPage - 1)}><ChevronLeft size={16}/></button><span>Page {currentPage + 1} of {pageCount}</span><button className="icon-button" aria-label="Next rules page" disabled={editing || busy || currentPage + 1 >= pageCount} onClick={() => changePage(currentPage + 1)}><ChevronRight size={16}/></button></div>
      {selectedCount > 0 && editable && <div className="review-selection-bar" role="region" aria-label="Selected rule actions">
        <div className="review-selection-main"><strong>{selectedCount} selected</strong><button className="text-button" disabled={busy} onClick={() => { setChecked({}); setBulkOptions(false); }}>Clear</button>
          <button className="secondary" disabled={busy || editing} onClick={() => setCategorizing({ rules: selectedRules, version: run.version })}>Categorize</button>
          <button className="secondary" disabled={busy || editing} aria-expanded={bulkOptions} onClick={() => setBulkOptions(!bulkOptions)}>More actions <ChevronDown size={14}/></button>
          <button className="primary" disabled={busy || editing || !actor.trim()} onClick={bulkApprove}><Check size={15}/>{busy ? 'Saving…' : `Approve ${selectedCount}`}</button></div>
        {!actor.trim() && <div className="review-selection-identity">{reviewerInput}<span className="muted">Enter your name to record approvals.</span></div>}
        {actor.trim() && <p className="review-selection-help">Reviewing as {actor} · Read each selected rule and its source before approving.</p>}
        {selectedFlagged > 0 && <p className="review-selection-help">{selectedFlagged} selected {selectedFlagged === 1 ? 'rule has' : 'rules have'} review warnings. You can approve these together; warnings remain visible. Missing configuration or invalid source evidence must still be resolved.</p>}
        {bulkOptions && <div className="review-selection-options">{actor.trim() && reviewerInput}<label>Batch note (optional)<input value={bulkNote} onChange={e => setBulkNote(e.target.value)} disabled={busy}/></label></div>}
        {error && <p className="error" role="alert">{error}</p>}
      </div>}
    </>}
    {categorizing && <CategorizeRulesDialog runId={run.id} version={categorizing.version} rules={categorizing.rules} actor={actor} onActorChange={onActorChange} onClose={() => setCategorizing(null)} onSave={changed => {
      setMessage(changed ? `${changed} ${changed === 1 ? 'rule categorized' : 'rules categorized'}. Complete categories leave “Needs categorization”; the rules remain awaiting approval.` : 'Categorization was already complete. No rules changed.');
      setCategorizing(null); setChecked({}); setSelected(''); setBulkOptions(false); reload();
    }}/>}
  </div>;
}
