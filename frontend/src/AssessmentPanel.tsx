import { useEffect, useState } from 'react';
import { jsonRequest } from './api';
import type { Connection, Run } from './api';
import { assessmentLabels, assessmentState, reviewFailure, reviewProgress } from './assessmentReadiness';
import type { AssessmentFilter } from './assessmentReadiness';

export default function AssessmentPanel({run, actor, connections, selectedIds, locked, reload, filter, onFilter}: {
  run: Run; actor: string; connections: Connection[]; selectedIds: string[]; locked: boolean; reload: () => void;
  filter: AssessmentFilter; onFilter: (value: AssessmentFilter) => void;
}) {
  const job = run.payload.assessment_job;
  const jev = connections.find(c => c.id === 'jev');
  const model = String(jev?.model || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [autoProcess, setAutoProcess] = useState(true);
  const running = !!job && ['queued', 'running'].includes(String(job.status));
  const classifying = ['queued', 'running'].includes(String(run.payload.classification_job?.status));
  const pending = run.payload.rules.filter(r => r.status === 'pending');
  const autoApproved = run.payload.rules.filter(r => r.status === 'approved' && r.review?.mode === 'automatic').length;
  const duplicatesRemoved = run.payload.rules.filter(r => r.status === 'ignored' && r.review?.mode === 'automatic_duplicate').length;
  const nonRulesRemoved = run.payload.rules.filter(r => r.status==='ignored' && r.review?.mode==='automatic_non_rule').length;
  const progress = reviewProgress(run.payload.rules,job);
  const failure = reviewFailure(job);
  const failedCount = progress.retryCount;
  const remaining = job?.pending;
  const canRetryFailed = job?.status === 'cancelled' || !Array.isArray(remaining) || remaining.length === 0;
  const originalProvider = ['anthropic','openai','litellm'].includes(String(run.config.provider)) ? String(run.config.provider) : 'anthropic';
  const [resolutionProvider, setResolutionProvider] = useState(originalProvider);
  const resolver = connections.find(c=>c.id===resolutionProvider);
  const defaultResolutionModel = String(run.config.provider===resolutionProvider ? run.config.model : resolver?.model || '');
  const [resolutionModel, setResolutionModel] = useState(defaultResolutionModel);
  useEffect(() => {setResolutionModel(defaultResolutionModel);}, [resolutionProvider, defaultResolutionModel]);
  const configured = jev?.credential_configured && model.trim() && resolver?.credential_configured && resolutionModel.trim();
  const totalChecked = progress.checked;
  const hasResults = progress.visible.some(rule => rule.assessment);
  const summary = (['ready', 'needs_correction', 'needs_review', 'stale', 'unassessed'] as const)
    .map(value => ({value, count: progress.visible.filter(rule => assessmentState(rule) === value).length}))
    .filter(item => (hasResults && item.count > 0) || filter === item.value);
  const request = async (cancel = false, resume = false, scope: 'all' | 'selected' | 'failed' = 'all') => {
    setBusy(true); setError('');
    try {
      await jsonRequest(`/api/analysis/${run.id}/${cancel ? 'cancel-assessment' : 'assess'}`, {
        version: run.version, actor: actor.trim() || 'User', ...(cancel?{job_id:job?.id}:{}), ...(!cancel && {
          model: resume ? String(job?.model || model).trim() : model.trim(), scope, sample_size: 25, rule_ids: scope === 'selected' ? selectedIds : [], resume, auto_process: autoProcess,
          ...(!resume && {preparation_provider: resolutionProvider, preparation_model: resolutionModel.trim()}),
        }),
      });
      reload();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <section className="assessment-panel" aria-label="Automatic rule review">
    <div className="section-heading"><div><h3>Automatic review</h3>
      <p>The app fills in rule details and checks them against the guide. You only need to review what it cannot resolve.</p></div></div>
    {(autoApproved>0||duplicatesRemoved>0||nonRulesRemoved>0)&&<p role="status"><strong>{autoApproved} auto-approved · {duplicatesRemoved} duplicates set aside · {nonRulesRemoved} background items set aside</strong> · Originals and decision history are saved.</p>}
    {!!summary.length && !running && <p className="muted">Current results for rules awaiting approval:</p>}
    {!!summary.length && !(running&&job?.phase==='resolve') && <div className="assessment-summary">{summary.map(({value, count: total}) =>
      <button key={value} className={`secondary ${filter === value ? 'selected' : ''}`} aria-pressed={filter === value} disabled={locked} onClick={() => onFilter(filter === value ? 'all' : value)}>
        {total} {assessmentLabels[value].toLowerCase()}
      </button>)}</div>}
    {running ? <><div className="action-row"><p role="status">{job?.phase === 'resolve' ? `Step 1 of 2: Filling in rule details — ${String(job.prepared)} of ${String(job.total)}. ${String(job.updated)} updated automatically.` : `Step 2 of 2: Checking which rules to keep and approve — ${String(job?.processed)} of ${String(job?.total)}.`}</p>
      <button className="secondary" disabled={busy || locked} onClick={() => request(true)}>Stop review</button></div><p className="muted">No decisions are needed while checks run. You can browse the rules or come back later. Completed work is saved.</p></>
      : run.status === 'complete' && <><div className="assessment-controls">
        <button className="primary" disabled={busy || locked || classifying || !configured || !pending.length} onClick={() => request()}>{busy ? 'Starting…' : `${autoProcess?'Automatically review':'Check'} all pending rules (${pending.length})`}</button>
        {!!failedCount && canRetryFailed && <button className="secondary" disabled={busy || locked || classifying || !configured} onClick={() => request(false, false, 'failed')}>Retry incomplete checks ({failedCount})</button>}
        {!!selectedIds.length && <button className="secondary" disabled={busy || locked || classifying || !configured} onClick={() => request(false, false, 'selected')}>Review selected rules ({selectedIds.length})</button>}
        {(['failed','cancelled'].includes(String(job?.status)) && Number(job?.processing_version)>=2) && failure.canContinue && <button className="secondary" disabled={busy || locked || classifying || !jev?.credential_configured || !job?.model} onClick={() => request(false, true)}>Resume review</button>}
      </div>
      <p className="muted">{autoProcess?'Fills in missing details, approves rules that pass the checks, and sets aside identical duplicates and text that is not a requirement. You can undo these decisions.':'Fills in missing details and checks the rules. You decide which rules to approve or exclude.'} Includes pending rules outside your current filters. Finished checks are reused when still valid. AI usage charges may apply.</p>
      <details><summary>Review settings</summary><label className="checkbox-label"><input type="checkbox" checked={autoProcess} disabled={busy||locked} onChange={e=>setAutoProcess(e.target.checked)}/>Approve rules that pass the checks; set aside identical duplicates and text that contains no requirement</label><label>AI service for filling in rule details<select value={resolutionProvider} disabled={busy||locked} onChange={e=>setResolutionProvider(e.target.value)}><option value="anthropic">Claude / Anthropic</option><option value="openai">OpenAI</option><option value="litellm">LiteLLM</option></select></label><label>Model<input value={resolutionModel} disabled={busy||locked} onChange={e=>setResolutionModel(e.target.value)}/></label><p className="muted">To use a different model, start a new review with the main button above. Resume review keeps the previous model. Verification uses the connection saved in Connections.</p></details>
      {!configured && <p>Open Connections and configure the review service and selected AI model before starting.</p>}
      {classifying && <p>Rule types and workflows are being assigned. Wait for that to finish before starting a review.</p>}</>}
    {hasResults && !progress.preparing && <p role="status">{running?'This review: ': 'Current results: '}{totalChecked} rules checked and awaiting approval{progress.currentFailures > 0 && ` · ${progress.currentFailures} unfinished checks`}.</p>}
    {!!job?.updated_at&&<p className="muted">Last update: {new Date(String(job.updated_at)).toLocaleTimeString()}{Number(job.reused_prepared)>0&&` · ${String(job.reused_prepared)} previous rule-detail checks reused`}{Number(job.reused_assessments)>0&&` · ${String(job.reused_assessments)} checks reused`}.</p>}
    {job?.status==='cancelled'&&<p>Stopped. Completed work is saved. {Number(job.processing_version)>=2?'Choose Resume review to continue where it stopped, or start a new review to use different settings.':'Start a new review to reuse finished checks and retry the rest.'}</p>}
    {job?.status === 'complete' && <p className="muted">Last {job.scope === 'failed' ? 'retry' : 'review'}: {String(job.assessed)} checked{Number(job.updated) > 0 && ` · ${String(job.updated)} automatically improved`}{Number(job.failed) > 0 && ` · ${String(job.failed)} could not be checked`}{Number(job.skipped) > 0 && ` · ${String(job.skipped)} changed or reviewed rules skipped`}.</p>}
    {progress.currentFailures>0 && running && <p role="status">{progress.currentFailures} {progress.preparing?'rule updates':'checks'} could not finish. The review is continuing with other rules. Retry incomplete checks afterward; you do not need to make a manual decision yet.</p>}

    {job?.status === 'failed' && <p>This review stopped{job.phase === 'resolve' ? ` while filling in details, after ${Number(job.prepared)||0} of ${Number(job.total)||0} rules` : ''}. {Number(job.assessed)||0} rule checks completed before it stopped.</p>}
    {(error || job?.status === 'failed') && <p className="error" role="alert">{error || failure.message}</p>}
  </section>;
}
