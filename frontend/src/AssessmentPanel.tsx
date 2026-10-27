import { useState } from 'react';
import { jsonRequest } from './api';
import type { Connection, Run } from './api';
import { assessmentLabels, assessmentState } from './assessmentReadiness';
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
  const running = !!job && ['queued', 'running'].includes(String(job.status));
  const classifying = ['queued', 'running'].includes(String(run.payload.classification_job?.status));
  const pending = run.payload.rules.filter(r => r.status === 'pending');
  const configured = jev?.credential_configured && model.trim();
  const hasResults = pending.some(rule => rule.assessment);
  const summary = (['ready', 'needs_correction', 'needs_review', 'stale', 'unassessed'] as const)
    .map(value => ({value, count: pending.filter(rule => assessmentState(rule) === value).length}))
    .filter(item => (hasResults && item.count > 0) || filter === item.value);
  const request = async (cancel = false, resume = false, scope: 'all' | 'selected' = 'all') => {
    setBusy(true); setError('');
    try {
      await jsonRequest(`/api/analysis/${run.id}/${cancel ? 'cancel-assessment' : 'assess'}`, {
        version: run.version, actor: actor.trim() || 'User', ...(!cancel && {
          model: resume ? String(job?.model || model).trim() : model.trim(), scope, sample_size: 25, rule_ids: scope === 'selected' ? selectedIds : [], resume,
        }),
      });
      reload();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <section className="assessment-panel" aria-label="Review readiness">
    <div className="section-heading"><div><h3>Review readiness</h3>
      <p>Check for missing information, conflicting requirements, and duplicates before approving rules.</p></div></div>
    {!!summary.length && <div className="assessment-summary">{summary.map(({value, count: total}) =>
      <button key={value} className={`secondary ${filter === value ? 'selected' : ''}`} aria-pressed={filter === value} disabled={locked} onClick={() => onFilter(filter === value ? 'all' : value)}>
        {total} {assessmentLabels[value].toLowerCase()}
      </button>)}</div>}
    {running ? <div className="action-row"><p role="status">Checked {String(job?.processed)} of {String(job?.total)} rules. You can review results as they arrive.</p>
      <button className="secondary" disabled={busy || locked} onClick={() => request(true)}>Stop checking</button></div>
      : run.status === 'complete' && <><div className="assessment-controls">
        <button className="primary" disabled={busy || locked || classifying || !configured || !pending.length} onClick={() => request()}>{busy ? 'Starting…' : `Check all rules (${pending.length})`}</button>
        {!!selectedIds.length && <button className="secondary" disabled={busy || locked || classifying || !configured} onClick={() => request(false, false, 'selected')}>Check selected ({selectedIds.length})</button>}
        {job?.status === 'failed' && job.reason !== 'configuration_required' && <button className="secondary" disabled={busy || locked || classifying || !jev?.credential_configured || !job.model} onClick={() => request(false, true)}>Continue checking</button>}
      </div>
      <p className="muted">Checks all pending rules in this draft, including rules outside the current filters. New analyses include these checks automatically. Usage charges may apply.</p>
      {!configured && <p>Set up automated checks in Connections to get started.</p>}
      {classifying && <p>Classification is in progress. You can check these rules when it finishes.</p>}</>}
    {job?.status === 'complete' && <p role="status">Check complete: {String(job.assessed)} rules checked{Number(job.skipped) > 0 && ` · ${String(job.skipped)} skipped because they changed or were already reviewed`}.</p>}
    {(error || job?.status === 'failed') && <p className="error" role="alert">{error || (job?.reason === 'configuration_required' ? 'Set up automated checks in Connections, then check all rules.' : 'Checks could not finish. Completed results are saved. Continue checking to try again; if the problem persists, contact your administrator.')}</p>}
  </section>;
}
