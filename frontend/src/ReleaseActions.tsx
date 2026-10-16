import { useRef, useState } from 'react';
import { jsonRequest } from './api';
import type { Release, Run } from './api';

export default function ReleaseActions({release, activeId, actor, onDraft, reload}: {
  release: Release; activeId: string | null; actor: string;
  onDraft: (run: Run) => void; reload: () => void;
}) {
  const requestId = useRef(crypto.randomUUID());
  const [action, setAction] = useState<'unpublish' | 'activate' | null>(null);
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const edit = async () => {
    setError('');
    if (!actor.trim()) { setError('Enter your reviewer name above to create a draft.'); return; }
    setBusy(true);
    try {
      const draft = await jsonRequest<Run>(`/api/releases/${release.id}/draft`, {actor, request_id: requestId.current});
      requestId.current = crypto.randomUUID();
      onDraft(draft);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const changeActive = async () => {
    setError('');
    if (!actor.trim() || !reason.trim()) { setError('Enter your reviewer name above and a reason below.'); return; }
    setBusy(true);
    try {
      await jsonRequest(`/api/releases/${release.id}/${action}`, {actor, note: reason, expected_active_id: activeId});
      setMessage(action === 'unpublish' ? 'Release unpublished. Its history is preserved.' : 'Release restored as active.');
      setAction(null); setReason(''); reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <div className="release-actions">
    <div className="action-row">
      <button className="secondary" disabled={busy} onClick={edit}>Edit as new draft</button>
      <button className="text-button" disabled={busy} onClick={() => {setAction(release.id === activeId ? 'unpublish' : 'activate'); setError(''); setMessage('');}}>
        {release.id === activeId ? 'Unpublish' : 'Restore as active'}
      </button>
      <small className="muted">Editing keeps the current release active until you publish your changes.</small>
    </div>
    {action && <div className="notice">
      <strong>{action === 'unpublish' ? `Unpublish ${release.name}?` : `Restore ${release.name} as active?`}</strong>
      <p>{action === 'unpublish'
        ? 'This retailer will have no active release. Saved versions, exports and scenarios pinned to this release remain available. To change rules, use Edit as new draft.'
        : 'This version will become the active release for this retailer. Previous releases remain in history.'}</p>
      <label>Reason<input value={reason} onChange={e => setReason(e.target.value)} placeholder="Why are you changing the active release?"/></label>
      <div className="action-row"><button className="primary" disabled={busy} onClick={changeActive}>{action === 'unpublish' ? 'Confirm unpublish' : 'Confirm restore'}</button><button className="secondary" disabled={busy} onClick={() => setAction(null)}>Cancel</button></div>
    </div>}
    {error && <p className="error" role="alert">{error}</p>}
    {message && <p className="notice" role="status">{message}</p>}
  </div>;
}
