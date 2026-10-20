import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { formatDate, jsonRequest } from './api';
import type { Run, Workflow } from './api';

export const runLabels: Record<string,string> = {queued:'Queued',running:'Analyzing',failed:'Stopped',cancelled:'Cancelled',complete:'Draft',published:'Published',deleted:'Deleted'};
const versionName = (run: Run, workflow: Workflow) => {
  const release = workflow.releases.find(r => r.run_id === run.id);
  const deletion = run.config.deletion as {release_name?:string} | undefined;
  const name = release?.name || deletion?.release_name || (run.config.source_release_name ? `Draft of ${String(run.config.source_release_name)}` : run.config.provider === 'manual' ? 'Manual draft' : 'Analysis');
  return `${name} · ${new Date(run.created_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})} · ${runLabels[run.status] || run.status}${release?.id === workflow.active_release_id ? ' · Active' : ''}`;
};

export default function VersionControls({workflow, active, locked, actor, onActorChange, onSelect, onDelete, onRestore, onReleases}: {
  workflow: Workflow; active?: Run; locked: boolean; actor: string; onActorChange: (name:string)=>void;
  onSelect: (id:string)=>void; onDelete: (id:string)=>void; onRestore: (run:Run)=>void; onReleases:()=>void;
}) {
  const [confirm, setConfirm] = useState<Run|null>(null);
  const [showDeleted,setShowDeleted] = useState(false);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const selectedRelease = workflow.releases.find(r=>r.run_id === active?.id);
  const liveRelease = workflow.releases.find(r=>r.id === workflow.active_release_id);
  const classificationRunning = ['queued','running'].includes(String(active?.payload.classification_job?.status));
  const deleteBlocker = locked ? 'Save or cancel rule edits first.' : active && ['queued','running'].includes(active.status) ? 'Stop analysis before deleting.' : classificationRunning ? 'Stop classification before deleting.' : selectedRelease?.id === workflow.active_release_id ? 'Unpublish this active release before deleting.' : '';
  const deleted = workflow.deleted_runs || [];
  const change = async (run:Run, action:'delete'|'restore') => {
    if (!actor.trim()) {setError('Enter your name.'); return;}
    setBusy(true); setError('');
    try {
      const result = await jsonRequest<Run>(`/api/analysis/${run.id}/${action}`,{version:run.version,actor});
      setConfirm(null);
      if(action === 'delete') onDelete(run.id); else onRestore(result);
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  };
  return <div className="version-workspace">
    <div className="guide-context-bar">
      {active ? <label>Analysis / rule draft<select aria-label="Analysis / rule draft" value={active.id} disabled={busy || locked} onChange={e=>{setConfirm(null);setError('');onSelect(e.target.value);}}>{workflow.runs.map(run=><option key={run.id} value={run.id}>{versionName(run,workflow)}</option>)}</select></label> : <span>No analyses or drafts</span>}
      {selectedRelease && <span className="version-effective">Release effective {formatDate(selectedRelease.effective_date)}</span>}
      <div className="version-actions">{active && <button className="text-button" disabled={busy || !!deleteBlocker} title={deleteBlocker || 'Move this version to Deleted analyses / drafts'} onClick={()=>{setConfirm(active);setError('');}}><Trash2 size={13}/> Delete analysis / draft</button>}{deleted.length>0 && <button className="text-button" onClick={()=>{setShowDeleted(v=>!v);setError('');}}>Deleted analyses / drafts ({deleted.length})</button>}</div>
    </div>
    <div className="version-release-context"><span>{liveRelease ? <>Active retailer release: <strong>{liveRelease.name}</strong> · Effective {formatDate(liveRelease.effective_date)}</> : 'No active retailer release'}</span><button className="text-button" onClick={onReleases}>Manage releases</button>{deleteBlocker && <span className="muted">{deleteBlocker}</span>}</div>
    {(confirm || showDeleted) && <div className="version-management"><label>Your name<input value={actor} disabled={busy} onChange={e=>onActorChange(e.target.value)} autoComplete="name"/></label>
      {confirm && <div className="version-delete-confirm"><strong>Delete {versionName(confirm,workflow)}?</strong><p>{confirm.payload.rules.length} rules will move to Deleted analyses / drafts. You can restore this version later. Saved release exports and evaluation history are retained.</p><div className="action-row"><button className="secondary" disabled={busy || locked || !actor.trim()} onClick={()=>change(confirm,'delete')}>Confirm delete</button><button className="text-button" disabled={busy} onClick={()=>setConfirm(null)}>Cancel</button></div></div>}
      {showDeleted && <div className="deleted-versions">{deleted.length===0 ? <p>No deleted versions.</p> : deleted.map(run=><div key={run.id}><span>{versionName(run,workflow)} · {run.payload.rules.length} rules</span><button className="secondary" disabled={busy || locked || !actor.trim()} onClick={()=>change(run,'restore')}>Restore</button></div>)}</div>}
    </div>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
