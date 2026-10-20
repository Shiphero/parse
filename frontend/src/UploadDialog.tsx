import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { AlertCircle, FileText, LoaderCircle, Upload, X } from 'lucide-react';
import { fileSize, request, useRemote } from './api';
import type { Guide, Library, UploadResult } from './api';

export default function UploadDialog({ library, retailer, initialGuide, onClose, onUploaded }: {
  library: Library; retailer: string; initialGuide?: Guide; onClose: () => void; onUploaded: (result: UploadResult) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState(initialGuide?.title || '');
  const [selectedRetailer, setSelectedRetailer] = useState(retailer);
  const [mode, setMode] = useState(initialGuide ? 'update' : '');
  const [previousId, setPreviousId] = useState(initialGuide?.id || '');
  const choices = useRemote<Guide[]>(`/api/retailers/${encodeURIComponent(selectedRetailer || '_')}/guide-choices`);
  const selectedGuide = choices.data?.find(g=>g.id===previousId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  useEffect(() => { const element = dialog.current!; element.showModal(); return () => element.close(); }, []);
  const choose = (files: FileList | null) => {
    if (busy) return;
    setError('');
    if (!files?.length) return;
    if (files.length > 1) { setError('Choose one guide at a time.'); return; }
    const next = files[0];
    if (!next.name.toLowerCase().endsWith('.pdf')) { setError('Choose the original PDF guide.'); return; }
    if (next.size > library.max_upload_mb * 1024 * 1024) { setError(`The upload limit is ${library.max_upload_mb} MB per PDF.`); return; }
    setFile(next);
    if (!title) setTitle(next.name.replace(/\.pdf$/i, '').slice(0, 250));
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file || busy || !mode || (mode === 'update' && !selectedGuide)) return;
    const form = new FormData(event.currentTarget);
    form.set('file', file); form.set('title', mode === 'update' ? selectedGuide!.title : title.trim());
    if(mode === 'update') form.set('previous_guide_id', previousId);
    if (!form.get('effective_date')) form.delete('effective_date');
    setBusy(true); setError('');
    try { onUploaded(await request<UploadResult>('/api/guides', { method: 'POST', body: form })); }
    catch (e) { setError(e instanceof Error ? e.message : 'Upload failed. Please try again.'); setBusy(false); }
  };
  return <dialog ref={dialog} className="upload-dialog" aria-labelledby="upload-title" onCancel={e => { e.preventDefault(); if (!busy) onClose(); }}>
    <div className="dialog-heading"><div><h2 id="upload-title">Upload document</h2></div><button className="icon-button" onClick={onClose} disabled={busy} aria-label="Close upload"><X size={20}/></button></div>
    <form onSubmit={submit}><fieldset disabled={busy}>
      <div className="form-field"><label htmlFor="retailer">Retailer <span>*</span></label><select id="retailer" name="retailer_id" value={selectedRetailer} onChange={e => {setSelectedRetailer(e.target.value);setPreviousId('');setMode('');setTitle('');}} required><option value="" disabled>Choose a retailer</option>{library.retailers.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></div>
      <div className="form-field"><label htmlFor="upload-kind">Upload type</label><select id="upload-kind" required value={mode} onChange={e=>{setMode(e.target.value);setPreviousId('');setTitle(file?.name.replace(/\.pdf$/i,'').slice(0,250)||'');}}><option value="" disabled>Choose upload type</option><option value="update" disabled={!choices.data?.length}>New edition of an existing guide</option><option value="new">Separate guide</option></select></div>
      {choices.error && <div className="error" role="alert">Unable to load existing guides. <button type="button" onClick={choices.reload}>Retry</button></div>}
      {mode === 'update' && <div className="form-field"><label htmlFor="previous-guide">Guide to update</label><select id="previous-guide" value={previousId} required onChange={e=>{setPreviousId(e.target.value);setTitle(choices.data?.find(g=>g.id===e.target.value)?.title || '');}}><option value="" disabled>Choose a guide</option>{choices.data?.map(g=><option key={g.id} value={g.id}>{g.title} · {g.version_label || `Edition ${g.edition_number}`}</option>)}</select><small>The existing PDF and rules remain available.</small></div>}
      <div className={`dropzone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`} onDragOver={e => { e.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files); }}>
        <input ref={input} type="file" accept="application/pdf,.pdf" className="visually-hidden" tabIndex={-1} aria-label="Choose PDF" onChange={e => choose(e.target.files)}/>
        {file ? <><FileText size={26}/><div className="selected-file"><strong>{file.name}</strong><span>{fileSize(file.size)} · Original PDF</span></div><button type="button" className="text-button" onClick={() => input.current?.click()}>Change</button></> : <><Upload size={25}/><strong>Drop your PDF here</strong><span>or <button type="button" className="inline-button" onClick={() => input.current?.click()}>browse files</button></span><small>PDF · Up to {library.max_upload_mb} MB · One guide at a time</small></>}
      </div>
      {mode !== 'update' && <div className="form-field"><label htmlFor="guide-title">Guide title <span>*</span></label><input id="guide-title" name="title" value={title} onChange={e => setTitle(e.target.value)} maxLength={250} placeholder="e.g. Packaging Guide" required/></div>}
      <div className="form-row"><div className="form-field"><label htmlFor="version">Edition <small>Optional</small></label><input id="version" name="version_label" maxLength={100} placeholder="e.g. 2025 edition"/></div><div className="form-field"><label htmlFor="effective-date">Document effective date <small>Optional</small></label><input id="effective-date" name="effective_date" type="date"/></div></div>
      <p className="form-hint">Use the date stated in the guide. Leave it blank if you’re unsure.</p>
    </fieldset>{error && <div className="error" role="alert"><AlertCircle size={17}/><span>{error}</span></div>}
    <div className="dialog-footer"><span><FileText size={14}/> Your original file is preserved</span><button type="submit" className="primary" disabled={!file || !selectedRetailer || !mode || (mode === 'update' ? !selectedGuide : !title.trim()) || busy}>{busy ? <><LoaderCircle className="spin" size={16}/> Uploading…</> : <><Upload size={16}/> {mode === 'update' ? 'Upload edition' : 'Upload guide'}</>}</button></div></form>
  </dialog>;
}
