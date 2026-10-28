import { useState } from 'react';
import { jsonRequest } from './api';
import type { Connection, Run } from './api';
import { assessmentLabels, assessmentState, reviewProgress } from './assessmentReadiness';
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
  const progress = reviewProgress(run.payload.rules,job);
  const failedCount = progress.retryCount;
  const remaining = job?.pending;
  const canRetryFailed = job?.status === 'cancelled' || !Array.isArray(remaining) || remaining.length === 0;
  const resolutionProvider = ['anthropic','openai'].includes(String(run.config.provider)) ? String(run.config.provider) : 'anthropic';
  const resolver = connections.find(c=>c.id===resolutionProvider);
  const configured = jev?.credential_configured && model.trim() && resolver?.credential_configured && (run.config.provider===resolutionProvider ? run.config.model : resolver.model);
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
        }),
      });
      reload();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <section className="assessment-panel" aria-label="Review readiness">
    <div className="section-heading"><div><h3>Automatic review</h3>
      <p>Let the app fix supported details, handle identical duplicates, and approve clear rules. Review only what remains unresolved.</p></div></div>
    {(autoApproved>0||duplicatesRemoved>0)&&<p role="status"><strong>{autoApproved} auto-approved · {duplicatesRemoved} duplicates set aside</strong> · Originals and decision history are saved.</p>}
    {!!summary.length && !(running&&job?.phase==='resolve') && <div className="assessment-summary">{summary.map(({value, count: total}) =>
      <button key={value} className={`secondary ${filter === value ? 'selected' : ''}`} aria-pressed={filter === value} disabled={locked} onClick={() => onFilter(filter === value ? 'all' : value)}>
        {total} {assessmentLabels[value].toLowerCase()}
      </button>)}</div>}
    {running ? <><div className="action-row"><p role="status">{job?.phase === 'resolve' ? `Step 1 of 2: Preparing rules — ${String(job.prepared)} of ${String(job.total)}. ${String(job.updated)} updated automatically.` : `Step 2 of 2: Checking accuracy and duplicates — ${String(job?.processed)} of ${String(job?.total)}.`}</p>
      <button className="secondary" disabled={busy || locked} onClick={() => request(true)}>Stop checking</button></div><p className="muted">No decisions are needed while checks run. You can browse the rules or come back later. Completed work is saved.</p></>
      : run.status === 'complete' && <><div className="assessment-controls">
        <button className="primary" disabled={busy || locked || classifying || !configured || !pending.length} onClick={() => request()}>{busy ? 'Starting…' : `${autoProcess?'Auto-process':'Check'} all rules (${pending.length})`}</button>
        {!!failedCount && canRetryFailed && <button className="secondary" disabled={busy || locked || classifying || !configured} onClick={() => request(false, false, 'failed')}>Retry failed checks ({failedCount})</button>}
        {!!selectedIds.length && <button className="secondary" disabled={busy || locked || classifying || !configured} onClick={() => request(false, false, 'selected')}>Resolve selected ({selectedIds.length})</button>}
        {(['failed','cancelled'].includes(String(job?.status)) && Number(job?.processing_version)>=2) && !['configuration_required','version_changed','repeated_invalid_responses'].includes(String(job?.reason)) && <button className="secondary" disabled={busy || locked || classifying || !jev?.credential_configured || !job?.model} onClick={() => request(false, true)}>Continue checking</button>}
      </div>
      <p className="muted">{autoProcess?'Applies verified fixes, sets aside identical duplicates and approves rules that pass the required checks. You can undo automatic decisions.':'Applies verified fixes and checks the rules; approvals and duplicate decisions remain yours.'} Completed work is reused when the rule and checks are unchanged. New analyses use automatic processing. Usage charges may apply.</p>
      <details><summary>Processing options</summary><label className="checkbox-label"><input type="checkbox" checked={autoProcess} disabled={busy||locked} onChange={e=>setAutoProcess(e.target.checked)}/>Automatically approve clear rules and set aside identical duplicates</label></details>
      {!configured && <p>Set up automated checks in Connections to get started.</p>}
      {classifying && <p>Classification is in progress. You can check these rules when it finishes.</p>}</>}
    {hasResults && !progress.preparing && <p role="status">{running?'This run: ': 'Saved results: '}{totalChecked} pending rules checked{progress.currentFailures > 0 && ` · ${progress.currentFailures} checks need retrying`}.</p>}
    {!!job?.updated_at&&<p className="muted">Last progress: {new Date(String(job.updated_at)).toLocaleTimeString()}{Number(job.reused_prepared)>0&&` · ${String(job.reused_prepared)} preparation results reused`}{Number(job.reused_assessments)>0&&` · ${String(job.reused_assessments)} checks reused`}.</p>}
    {job?.status==='cancelled'&&<p>Stopped. Completed work is saved. {Number(job.processing_version)>=2?'Continue this run, or start a new run to retry failed rules.':'Start a new run to reuse successful results and retry unfinished work.'}</p>}
    {job?.status === 'complete' && <p className="muted">Last {job.scope === 'failed' ? 'retry' : 'run'}: {String(job.assessed)} checked{Number(job.updated) > 0 && ` · ${String(job.updated)} automatically improved`}{Number(job.failed) > 0 && ` · ${String(job.failed)} could not be checked`}{Number(job.skipped) > 0 && ` · ${String(job.skipped)} changed or reviewed rules skipped`}.</p>}
    {progress.currentFailures>0 && <p role="status">{progress.currentFailures} {progress.preparing?'preparation attempts':'checks'} could not finish. {running?'Other rules are still being processed. Completed results are saved; failed rules can be retried afterward.':'Retry the failed rules. A failed automatic check does not itself require a manual policy decision.'}</p>}

    {(error || job?.status === 'failed') && <p className="error" role="alert">{error || (job?.reason === 'configuration_required' ? 'Set up automated checks in Connections, then check all rules.' : job?.reason === 'repeated_invalid_responses' ? 'Automatic preparation stopped after repeated unusable responses. Completed work is saved. Contact your administrator before retrying.' : job?.reason === 'version_changed' ? 'Automatic review has been updated. Start a new run using the button above. Completed work is saved.' : 'Checks could not finish. Completed results are saved. Continue checking to try again; if the problem persists, contact your administrator.')}</p>}
  </section>;
}
