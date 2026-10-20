import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Search, Upload, X } from 'lucide-react';
import { request } from './api';
import type { Library } from './api';
import RetailerIcon from './RetailerIcon';

export default function RetailersDialog({ retailers, onClose, onChanged }: {
  retailers: Library['retailers']; onClose: () => void;
  onChanged: (id: string, iconUrl: string | null) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  const changeIcon = async (retailer: Library['retailers'][number], file?: File) => {
    setError(''); setMessage('');
    if (file && file.size > 1024 * 1024) { setError('Choose an image no larger than 1 MB.'); return; }
    setBusy(retailer.id);
    try {
      const body = new FormData();
      if (file) body.append('file', file);
      const result = await request<{ icon_url: string | null }>(`/api/retailers/${retailer.id}/icon`, {
        method: file ? 'PUT' : 'DELETE', ...(file ? { body } : {}),
      });
      onChanged(retailer.id, result.icon_url);
      setMessage(`${retailer.name} icon ${file ? 'saved' : 'removed'}.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(''); }
  };
  const visible = retailers.filter(r => r.name.toLowerCase().includes(search.trim().toLowerCase()));
  return <dialog ref={dialog} className="upload-dialog retailers-dialog" aria-labelledby="retailers-title" onCancel={e => { if (busy) e.preventDefault(); else onClose(); }}>
    <div className="dialog-heading"><div><h2 id="retailers-title">Manage retailers</h2><p className="retailer-format-note">Icons: PNG, JPEG or WebP · Up to 1 MB</p></div><button className="icon-button" aria-label="Close retailers" disabled={!!busy} onClick={onClose}><X size={19}/></button></div>
    <div className="search-field retailer-manager-search"><Search size={16}/><input autoFocus aria-label="Search retailers to manage" placeholder="Find a retailer…" value={search} onChange={e => setSearch(e.target.value)}/></div>
    <div className="retailer-manager-list">{visible.map(r => <div className="retailer-manager-row" key={r.id}>
      <RetailerIcon retailer={r} large/><div className="retailer-manager-name"><strong>{r.name}</strong><small>{r.guide_count} {r.guide_count === 1 ? 'guide' : 'guides'}</small></div>
      <div className="retailer-manager-actions"><label className={`secondary icon-upload${busy ? ' disabled' : ''}`}>
        {busy === r.id ? <LoaderCircle className="spin" size={14}/> : <Upload size={14}/>}{r.icon_url ? 'Replace icon' : 'Upload icon'}
        <input type="file" accept="image/png,image/jpeg,image/webp" aria-label={`Upload icon for ${r.name}`} disabled={!!busy} onChange={e => { const file = e.currentTarget.files?.[0]; e.currentTarget.value = ''; if (file) void changeIcon(r, file); }}/>
      </label>{r.icon_url && <button className="icon-button" title={`Remove icon for ${r.name}`} aria-label={`Remove icon for ${r.name}`} disabled={!!busy} onClick={() => void changeIcon(r)}><X size={15}/></button>}</div>
    </div>)}{!visible.length && <p className="retailer-no-results">No retailers match.</p>}</div>
    {error && <p className="error" role="alert">{error}</p>}{message && <p className="retailer-save-message" role="status">{message}</p>}
    <div className="retailer-manager-footer"><button className="secondary" disabled={!!busy} onClick={onClose}>Done</button></div>
  </dialog>;
}
