import { useEffect, useState } from 'react';
import { AlertCircle, ArrowDown, ArrowUp, ArrowUpRight, Check, ChevronLeft, ChevronRight, LoaderCircle, Pencil, Plus, Search, Upload, X } from 'lucide-react';
import { jsonRequest, request, useRemote } from './api';
import type { Library } from './api';
import type { components } from './api.generated';
import RetailerIcon from './RetailerIcon';

type Retailer = Library['retailers'][number];
type Edit = { id: string; original: string; name: string };
export default function RetailersPage({ onChanged, onOpenGuides }: {
  onChanged: () => void; onOpenGuides: (id: string) => void;
}) {
  const remote = useRemote<Retailer[]>('/api/retailers', 5000);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState<'name' | 'guides'>('name');
  const [descending, setDescending] = useState(false);
  const [page, setPage] = useState(0);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [edit, setEdit] = useState<Edit | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const filtered = (remote.data || []).filter(r => r.name.toLowerCase().includes(search.trim().toLowerCase())
    && (filter === 'all' || (filter === 'with' ? r.guide_count > 0 : r.guide_count === 0)))
    .sort((a, b) => (sort === 'name' ? a.name.localeCompare(b.name) : a.guide_count - b.guide_count || a.name.localeCompare(b.name)) * (descending ? -1 : 1));
  const pages = Math.max(1, Math.ceil(filtered.length / 50));
  useEffect(() => { if (page >= pages) setPage(pages - 1); }, [page, pages]);
  const changed = (text: string) => { remote.reload(); onChanged(); setMessage(text); };
  const start = (id: string) => { setBusy(id); setError(''); setMessage(''); };
  const saveName = async () => {
    const current = edit;
    start(current?.id || 'new');
    try {
      const result = current
        ? await jsonRequest<Retailer>(`/api/retailers/${current.id}`, {name: current.name, expected_name: current.original} satisfies components['schemas']['RetailerUpdate'], 'PUT')
        : await jsonRequest<Retailer>('/api/retailers', {name} satisfies components['schemas']['RetailerInput']);
      setEdit(null); setAdding(false); setName('');
      if (!current) { setSearch(''); setFilter('all'); setPage(0); }
      changed(`${result.name} ${current ? 'updated' : 'added'}.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(''); }
  };
  const changeIcon = async (retailer: Retailer, file?: File) => {
    setError(''); setMessage('');
    if (file && file.size > 1024 * 1024) { setError('Choose an image no larger than 1 MB.'); return; }
    start(retailer.id);
    try {
      const body = new FormData();
      if (file) body.append('file', file);
      await request<components['schemas']['RetailerIconResult']>(`/api/retailers/${retailer.id}/icon`, {method: file ? 'PUT' : 'DELETE', ...(file ? {body} : {})});
      changed(`${retailer.name} icon ${file ? 'saved' : 'removed'}.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(''); }
  };
  const changeSort = (field: 'name' | 'guides') => { setSort(field); setDescending(sort === field ? !descending : false); setPage(0); };
  const sortIcon = (field: 'name' | 'guides') => sort === field && (descending ? <ArrowDown size={13}/> : <ArrowUp size={13}/>);
  return <>
    <div className="page-heading library-heading"><div className="library-title"><h1>Retailers</h1><span className="library-total">{remote.data?.length ?? '—'}</span></div><button className="primary" disabled={!!busy || adding} onClick={() => { setAdding(true); setEdit(null); setError(''); setMessage(''); }}><Plus size={16}/> Add retailer</button></div>
    {adding && <form className="retailer-create-form" onSubmit={e => { e.preventDefault(); void saveName(); }}>
      <label htmlFor="new-retailer-name">Retailer name</label><input autoFocus id="new-retailer-name" placeholder="Enter retailer name" maxLength={100} required value={name} disabled={!!busy} onChange={e => setName(e.target.value)}/>
      <button className="primary" disabled={!!busy || !name.trim()}>{busy === 'new' ? <LoaderCircle size={14} className="spin"/> : <Plus size={14}/>} Add retailer</button><button type="button" className="secondary" disabled={!!busy} onClick={() => { setAdding(false); setName(''); setError(''); }}>Cancel</button>
    </form>}
    {(error || remote.error) && <div className="error" role="alert"><AlertCircle size={16}/><span>{error || remote.error}</span>{remote.error && <button onClick={remote.reload}>Retry</button>}</div>}
    {message && <div className="retailer-page-notice" role="status"><Check size={15}/>{message}<button className="icon-button" aria-label="Dismiss notification" onClick={() => setMessage('')}><X size={14}/></button></div>}
    <section className="library-panel retailer-page-panel" aria-label="Retailer management">
      <div className="library-toolbar"><div className="search-field"><Search size={16}/><input aria-label="Search retailers" placeholder="Search retailers…" value={search} onChange={e => { setSearch(e.target.value); setPage(0); }}/>{search && <button className="icon-button" aria-label="Clear retailer search" onClick={() => {setSearch(''); setPage(0);}}><X size={14}/></button>}</div><select className="status-filter" aria-label="Filter retailers by guides" value={filter} onChange={e => {setFilter(e.target.value); setPage(0);}}><option value="all">All retailers</option><option value="with">With guides</option><option value="without">Without guides</option></select><span className="result-count">{filtered.length} {filtered.length === 1 ? 'retailer' : 'retailers'}</span></div>
      {!remote.data && !remote.error && <div className="loading"><LoaderCircle size={18} className="spin"/> Loading retailers…</div>}
      {remote.data && !filtered.length && <div className="empty-library"><h2>No matching retailers</h2>{(search || filter !== 'all') && <button className="secondary" onClick={() => {setSearch(''); setFilter('all');}}>Clear filters</button>}</div>}
      {filtered.length > 0 && <div className="retailer-table-wrap"><table className="guide-table retailer-management-table"><thead><tr><th scope="col" aria-sort={sort === 'name' ? descending ? 'descending' : 'ascending' : 'none'}><button className="table-sort" onClick={() => changeSort('name')}>Retailer{sortIcon('name')}</button></th><th scope="col" aria-sort={sort === 'guides' ? descending ? 'descending' : 'ascending' : 'none'}><button className="table-sort" onClick={() => changeSort('guides')}>Guides{sortIcon('guides')}</button></th><th scope="col">Icon</th><th scope="col">Actions</th></tr></thead><tbody>{filtered.slice(page * 50, (page + 1) * 50).map(r => <tr key={r.id}>
        <td><div className="retailer-name-cell"><RetailerIcon retailer={r} large/>{edit?.id === r.id ? <form className="retailer-rename-form" onSubmit={e => {e.preventDefault(); void saveName();}}><input autoFocus aria-label={`Name for ${r.name}`} maxLength={100} required value={edit.name} disabled={!!busy} onChange={e => setEdit({...edit, name:e.target.value})}/><button className="icon-button" aria-label={`Save name for ${r.name}`} title="Save name" disabled={!!busy || !edit.name.trim()}><Check size={16}/></button><button type="button" className="icon-button" aria-label="Cancel rename" title="Cancel rename" disabled={!!busy} onClick={() => {setEdit(null); setError('');}}><X size={16}/></button></form> : <strong>{r.name}</strong>}</div></td>
        <td><button className="retailer-guide-count" aria-label={`View guides for ${r.name}`} onClick={() => onOpenGuides(r.id)}>{r.guide_count}<ArrowUpRight size={13}/></button></td>
        <td><div className="retailer-icon-controls"><label className={`secondary icon-upload${busy ? ' disabled' : ''}`} title="PNG, JPEG or WebP · Up to 1 MB">{busy === r.id ? <LoaderCircle size={13} className="spin"/> : <Upload size={13}/>} {r.icon_url ? 'Replace' : 'Upload'}<input type="file" accept="image/png,image/jpeg,image/webp" aria-label={`Upload icon for ${r.name}`} disabled={!!busy} onChange={e => {const file=e.currentTarget.files?.[0]; e.currentTarget.value=''; if (file) void changeIcon(r,file);}}/></label>{r.icon_url && <button className="icon-button" title="Remove icon" aria-label={`Remove icon for ${r.name}`} disabled={!!busy} onClick={() => void changeIcon(r)}><X size={14}/></button>}</div></td>
        <td><button className="secondary retailer-rename-button" disabled={!!busy || !!edit || adding} onClick={() => {setEdit({id:r.id, original:r.name, name:r.name}); setError(''); setMessage('');}}><Pencil size={13}/> Rename<span className="visually-hidden"> {r.name}</span></button></td>
      </tr>)}</tbody></table></div>}
      <div className="pagination"><span>{filtered.length ? page * 50 + 1 : 0}–{Math.min((page + 1) * 50, filtered.length)} of {filtered.length}</span><span className="retailer-icon-hint">Icons: PNG, JPEG or WebP · Up to 1 MB</span><div><button className="icon-button" aria-label="Previous retailers" disabled={page === 0} onClick={() => setPage(p => p - 1)}><ChevronLeft size={16}/></button><span className="retailer-page-number">{page + 1} / {pages}</span><button className="icon-button" aria-label="Next retailers" disabled={page + 1 >= pages} onClick={() => setPage(p => p + 1)}><ChevronRight size={16}/></button></div></div>
    </section>
  </>;
}
