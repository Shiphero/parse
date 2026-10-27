import { useEffect, useState } from 'react';
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
  const [model, setModel] = useState(String(job?.model || jev?.model || ''));
  const [scope, setScope] = useState('sample');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setModel(String(job?.model || jev?.model || '')); }, [job?.model, jev?.model]);
  const running = !!job && ['queued', 'running'].includes(String(job.status));
  const classifying = ['queued', 'running'].includes(String(run.payload.classification_job?.status));
  const pending = run.payload.rules.filter(r => r.status === 'pending');
  const count = scope === 'sample' ? Math.min(25, pending.length) : scope === 'selected' ? selectedIds.length : pending.length;
  const configured = jev?.credential_configured && model.trim();
  const request = async (cancel = false, resume = false) => {
    setBusy(true); setError('');
    try {
      await jsonRequest(`/api/analysis/${run.id}/${cancel ? 'cancel-assessment' : 'assess'}`, {
        version: run.version, actor: actor.trim() || 'User', ...(!cancel && {
          model: model.trim(), scope, sample_size: 25, rule_ids: scope === 'selected' ? selectedIds : [], resume,
        }),
      });
      reload();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return <section className="assessment-panel" aria-label="Jev review assessment">
    <div className="section-heading"><div><h3>Jev review assessment <span className="status-badge">Preview</span></h3>
      <p>Find which rules are ready and what the others need. Rule definitions and approvals stay unchanged.</p></div></div>
    <div className="assessment-summary">{(['ready', 'needs_correction', 'needs_review', 'stale', 'unassessed'] as const).map(value =>
      <button key={value} className={`secondary ${filter === value ? 'selected' : ''}`} disabled={locked} onClick={() => onFilter(filter === value ? 'all' : value)}>
        {pending.filter(r => assessmentState(r) === value).length} {assessmentLabels[value].toLowerCase()}
      </button>)}</div>
    {running ? <div className="action-row"><p role="status">Assessed {String(job?.processed)} of {String(job?.total)} rules. Results are saved as they finish.</p>
      <button className="secondary" disabled={busy || locked} onClick={() => request(true)}>Stop assessment</button></div>
      : run.status === 'complete' && <><div className="assessment-controls">
        <label>Assess<select value={scope} disabled={busy || locked} onChange={e => setScope(e.target.value)}>
          <option value="sample">Varied sample (up to 25 pending rules)</option><option value="selected">Selected pending rules ({selectedIds.length})</option><option value="all">All pending rules ({pending.length})</option>
        </select></label>
        <label>Jev model<input value={model} disabled={busy || locked} onChange={e => setModel(e.target.value)} placeholder="Model ID"/></label>
        <button className="primary" disabled={busy || locked || classifying || !configured || !count} onClick={() => request()}>{busy ? 'Starting…' : `Assess ${count} rules`}</button>
        {job?.status === 'failed' && <button className="secondary" disabled={busy || locked || classifying || !configured || model.trim() !== job.model} onClick={() => request(false, true)}>Resume assessment</button>}
      </div>
      <p className="muted">Sends rule definitions, source text from cited and neighboring pages, and similar proposals to Jev. API charges apply. Images are not sent.</p>
      {!configured && <p>Add a Jev API key and model in Connections to assess rules.</p>}
      {classifying && <p>Wait for classification to finish before assessing the results.</p>}</>}
    {job?.status === 'complete' && <p role="status">Preview complete: {String(job.assessed)} assessed · {String(job.skipped)} changed or decided rules skipped.</p>}
    {(error || job?.status === 'failed') && <p className="error" role="alert">{error || String(job?.error)}</p>}
    <p className="muted">“Ready” is a recommendation, not an approval. Model confidence is not measured accuracy. Missing evidence and unresolved review issues override a high score.</p>
  </section>;
}
