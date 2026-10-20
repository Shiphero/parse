import { useState } from 'react';
import { AlertCircle, ArrowLeft, Download, LoaderCircle, Pencil, RefreshCw } from 'lucide-react';
import WorkflowPanel from './WorkflowPanel';
import GuideSource from './GuideSource';
import { fileSize, formatDate, jsonRequest, request, useRemote } from './api';
import type { GuideDetail } from './api';

export default function GuideViewer({ guideId, retailerName, onBack, notice }: {
  guideId: string; retailerName: (id: string) => string; onBack: () => void; notice: string;
}) {
  const { data: guide, error, reload } = useRemote<GuideDetail>(`/api/guides/${guideId}`, 4000);
  const [retrying, setRetrying] = useState(false);
  const [actionError, setActionError] = useState('');
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState('');
  const [originalTitle, setOriginalTitle] = useState('');
  const [savingTitle, setSavingTitle] = useState(false);
  const [renameError, setRenameError] = useState('');
  const rename = async () => {
    if (!title.trim() || savingTitle) return;
    setSavingTitle(true); setRenameError('');
    try {
      await jsonRequest(`/api/guides/${guideId}`, { title: title.trim(), expected_title: originalTitle }, 'PATCH');
      reload(); setRenaming(false);
    } catch (e) { setRenameError(e instanceof Error ? e.message : 'Unable to rename guide.'); }
    finally { setSavingTitle(false); }
  };
  const retry = async () => {
    setRetrying(true); setActionError('');
    try { await request(`/api/guides/${guideId}/retry`, { method: 'POST' }); reload(); }
    catch (e) { setActionError(e instanceof Error ? e.message : 'Unable to retry.'); }
    finally { setRetrying(false); }
  };
  return <div className="guide-workspace">
    <div className="guide-breadcrumb"><button className="back-link" onClick={onBack}><ArrowLeft size={14}/> Guides</button>{guide && <><span>/</span><span>{retailerName(guide.retailer_id)}</span></>}</div>
    {notice && <div className="notice" role="status">{notice}</div>}
    {error && <div className="error" role="alert"><AlertCircle size={16}/><span>{error}</span><button onClick={reload}>Retry</button></div>}
    {!guide && !error && <div className="loading"><LoaderCircle className="spin" size={18}/> Loading guide…</div>}
    {guide && <>
      <div className="guide-header"><div>{renaming ? <form className="guide-rename-form" onSubmit={e => {e.preventDefault(); void rename();}} onKeyDown={e => {if (e.key === 'Escape' && !savingTitle) {e.preventDefault(); setRenaming(false);}}}>
        <label className="visually-hidden" htmlFor="guide-title">Guide title</label>
        <input id="guide-title" value={title} onChange={e => setTitle(e.target.value)} maxLength={250} required autoFocus disabled={savingTitle}/>
        <button className="primary" type="submit" disabled={savingTitle || !title.trim()}>{savingTitle ? 'Saving…' : 'Save'}</button>
        <button className="secondary" type="button" disabled={savingTitle} onClick={() => setRenaming(false)}>Cancel</button>
        {renameError && <div className="error" role="alert">{renameError}</div>}
      </form> : <div className="guide-title-row"><h1>{guide.title}</h1><button className="text-button" aria-label="Rename guide" onClick={() => {setTitle(guide.title); setOriginalTitle(guide.title); setRenameError(''); setRenaming(true);}}><Pencil size={13}/> Rename</button></div>}<div className="guide-metadata">{guide.version_label && <span>{guide.version_label}</span>}<span>{guide.page_count === null ? 'Counting pages…' : `${guide.page_count} pages`}</span><span>{fileSize(guide.size_bytes)}</span><span>Document effective date: {formatDate(guide.effective_date, 'Not set')}</span><span>Uploaded {formatDate(guide.created_at)}</span></div></div><a className="secondary" href={`/api/guides/${guide.id}/original`} target="_blank" rel="noreferrer"><Download size={14}/> Original PDF</a></div>
      {['queued','preparing'].includes(guide.status) && <div className="guide-preparation-note" role="status"><LoaderCircle size={15} className="spin"/>{guide.status === 'queued' ? 'Preparation queued' : `Preparing pages · ${guide.processed_pages} / ${guide.page_count ?? '—'}`}</div>}
      {(guide.error || guide.attention_pages > 0) && <div className="attention-banner"><AlertCircle size={16}/><span>{guide.error || `${guide.attention_pages} pages need preparation retried.`}</span>{guide.can_retry && <button className="secondary" onClick={retry} disabled={retrying}><RefreshCw size={14}/>{retrying ? 'Retrying…' : 'Retry preparation'}</button>}</div>}
      {actionError && <div className="error" role="alert">{actionError}</div>}
      <WorkflowPanel guide={guide} source={<GuideSource guide={guide}/>}/>
    </>}
  </div>;
}
