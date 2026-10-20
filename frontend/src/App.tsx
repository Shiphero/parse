import { useEffect, useState } from 'react';
import { AlertCircle, ArrowDown, ArrowUp, ArrowUpDown, BookOpen, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, FileText, LoaderCircle, Plus, Search, Settings2, ShieldCheck, Store, X } from 'lucide-react';
import { fileSize, formatDate, statusNames, useRemote } from './api';
import type { Library, UploadResult } from './api';
import ParseBrand from './ParseBrand';
import RetailerIcon from './RetailerIcon';
import RetailersPage from './RetailersPage';
import GuideViewer from './GuideViewer';
import UploadDialog from './UploadDialog';
import ConnectionsDialog from './ConnectionsDialog';

type SortField = 'title' | 'retailer' | 'effective_date' | 'created_at';
function selectedGuide() { return window.location.hash.match(/^#guides\/([0-9a-f-]{36})(?:\/draft\/[0-9a-f-]{36})?$/i)?.[1] ?? null; }

export default function App() {
  const [retailer, setRetailer] = useState('');
  const [retailerSearch, setRetailerSearch] = useState('');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [sort, setSort] = useState<SortField>('created_at');
  const [direction, setDirection] = useState<'asc' | 'desc'>('desc');
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(50);
  const [upload, setUpload] = useState(false);
  const [revision, setRevision] = useState(0);
  const [guideId, setGuideId] = useState(selectedGuide);
  const [notice, setNotice] = useState('');
  const [connections, setConnections] = useState(false);
  const [showRetailers, setShowRetailers] = useState(() => window.location.hash === '#retailers');
  useEffect(() => { const t = window.setTimeout(() => setQuery(search), 250); return () => window.clearTimeout(t); }, [search]);
  useEffect(() => {
    const listener = () => { setGuideId(selectedGuide()); setShowRetailers(window.location.hash === '#retailers'); };
    if (window.location.hash === '#brand') window.history.replaceState(null, '', '#guides');
    window.addEventListener('hashchange', listener);
    return () => window.removeEventListener('hashchange', listener);
  }, []);
  const params = new URLSearchParams({ q: query, offset: String(offset), limit: String(limit), sort, direction });
  if (retailer) params.set('retailer_id', retailer);
  if (status) params.set('status', status);
  const { data: library, error, reload } = useRemote<Library>(`/api/guides?${params}`, 5000, revision);
  const [retailers, setRetailers] = useState<Library['retailers']>([]);
  useEffect(() => { if (library) setRetailers(library.retailers); }, [library]);
  useEffect(() => { if (library && offset > 0 && offset >= library.total) setOffset(Math.max(0, Math.ceil(library.total / limit) - 1) * limit); }, [library, offset, limit]);
  const retailerName = (id: string) => retailers.find(r => r.id === id)?.name || id;
  const totalGuides = retailers.reduce((sum, r) => sum + r.guide_count, 0);
  const selectedRetailer = retailers.find(r => r.id === retailer);
  const selectRetailer = (id: string) => { setRetailer(id); setOffset(0); setNotice(''); window.location.hash = 'guides'; };
  const openGuide = (id: string) => { setNotice(''); window.location.hash = `guides/${id}`; };
  const uploaded = (result: UploadResult) => {
    setUpload(false); setRevision(n => n + 1);
    setNotice(result.existing ? 'This guide is already in the library.' : 'Guide uploaded. Preparing pages…');
    window.location.hash = `guides/${result.guide.id}`;
  };
  const changeSort = (field: SortField) => { setSort(field); setDirection(sort === field && direction === 'asc' ? 'desc' : 'asc'); setOffset(0); };
  const sortHeader = (field: SortField, label: string) => <th scope="col" aria-sort={sort === field ? direction === 'asc' ? 'ascending' : 'descending' : 'none'}><button className="table-sort" onClick={() => changeSort(field)}>{label}{sort === field ? direction === 'asc' ? <ArrowUp size={13}/> : <ArrowDown size={13}/> : <ArrowUpDown size={13}/>}</button></th>;
  const filtersActive = Boolean(search || status || retailer);
  const resetFilters = () => { setSearch(''); setQuery(''); setStatus(''); selectRetailer(''); };
  const pageCount = Math.max(1, Math.ceil((library?.total || 0) / limit));
  const page = Math.floor(offset / limit) + 1;
  return <div className="shell"><aside className="sidebar">
    <a className="brand" aria-label="PARSE by ShipHero — guide library" href="#guides" onClick={() => selectRetailer('')}><ParseBrand/></a>
    <nav className="workspace-nav" aria-label="Guide library"><button className={`nav-item ${!retailer && !showRetailers ? 'active' : ''}`} onClick={() => selectRetailer('')} aria-current={!retailer && !showRetailers ? 'page' : undefined}><BookOpen size={17}/> All guides <span className="nav-count">{totalGuides}</span></button></nav>
    <div className="retailer-nav-heading"><span>Retailers</span><button className="icon-button" aria-label="Manage retailers" title="Manage retailers and icons" onClick={() => { window.location.hash = 'retailers'; }}><Settings2 size={15}/></button></div>
    <div className="sidebar-search"><Search size={14}/><input aria-label="Find retailer" placeholder="Find retailer…" value={retailerSearch} onChange={e => setRetailerSearch(e.target.value)}/>{retailerSearch && <button className="icon-button" aria-label="Clear retailer search" onClick={() => setRetailerSearch('')}><X size={12}/></button>}</div>
    <nav className="retailer-nav-list" aria-label="Retailers">{retailers.filter(r => r.name.toLowerCase().includes(retailerSearch.trim().toLowerCase())).map(r => <button key={r.id} className={`nav-item retailer-nav ${!showRetailers && retailer === r.id ? 'active' : ''}`} onClick={() => selectRetailer(r.id)} aria-current={!showRetailers && retailer === r.id ? 'page' : undefined}><RetailerIcon retailer={r}/><span className="retailer-nav-name">{r.name}</span><span className="nav-count">{r.guide_count}</span></button>)}</nav>
    <div className="sidebar-bottom"><a className={`nav-item ${showRetailers ? 'active' : ''}`} href="#retailers" aria-current={showRetailers ? 'page' : undefined}><Store size={16}/> Manage retailers</a><button className="nav-item" onClick={() => setConnections(true)}><Settings2 size={16}/> Connections</button><div className="private-label"><ShieldCheck size={12}/> Internal workspace</div></div>
  </aside><div className="main-wrap"><header className="topbar"><span><a href="#guides" onClick={() => selectRetailer('')}>Workspace</a><ChevronRight size={12}/><strong>{showRetailers ? 'Retailers' : guideId ? 'Guide details' : retailer ? retailerName(retailer) : 'All guides'}</strong></span></header><main className={guideId ? undefined : 'library-main'}>
    {showRetailers ? <RetailersPage onChanged={() => setRevision(n => n + 1)} onOpenGuides={id => { setSearch(''); setQuery(''); setStatus(''); selectRetailer(id); }}/> : guideId ? <GuideViewer library={library} onUploaded={uploaded} key={guideId} guideId={guideId} retailerName={retailerName} onBack={() => { setNotice(''); window.location.hash = 'guides'; }} notice={notice}/> : <>
      <div className="page-heading library-heading"><div className="library-title">{selectedRetailer && <RetailerIcon retailer={selectedRetailer} large/>}<h1>{selectedRetailer ? selectedRetailer.name : 'Routing guides'}</h1><span className="library-total">{selectedRetailer ? selectedRetailer.guide_count : totalGuides}</span></div><div className="library-heading-actions"><button className="secondary" onClick={() => { window.location.hash = 'retailers'; }}><Store size={15}/> Retailers</button><button className="primary" onClick={() => setUpload(true)} disabled={!library}><Plus size={16}/> Upload guide</button></div></div>
      <section className="library-panel" aria-label="Routing guide library">
        <div className="library-toolbar"><div className="search-field"><Search size={16}/><input aria-label="Search guides" placeholder="Search guides, retailers, versions…" value={search} onChange={e => { setSearch(e.target.value); setOffset(0); }}/>{search && <button className="icon-button" aria-label="Clear search" onClick={() => { setSearch(''); setOffset(0); }}><X size={14}/></button>}</div><select className="status-filter" aria-label="Filter by preparation status" value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}><option value="">All preparation states</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>{filtersActive && <button className="text-button clear-library-filters" onClick={resetFilters}>Clear filters</button>}<span className="result-count" aria-live="polite">{library ? `${library.total} ${library.total === 1 ? 'result' : 'results'}` : 'Loading…'}</span></div>
        {error && <div className="error library-error" role="alert"><AlertCircle size={16}/><span>{error}{library ? ' Showing the last available results.' : ''}</span><button onClick={reload}>Retry</button></div>}
        {!library && !error && <div className="loading"><LoaderCircle className="spin" size={18}/> Loading guides…</div>}
        {library && library.items.length === 0 && <div className="empty-library"><FileText size={28}/><h2>{filtersActive ? 'No matching guides' : 'No guides yet'}</h2>{filtersActive ? <button className="secondary" onClick={resetFilters}>Clear filters</button> : <button className="secondary" onClick={() => setUpload(true)}><Plus size={15}/> Upload guide</button>}</div>}
        {library && library.items.length > 0 && <div className="guide-table-wrap"><table className="guide-table"><thead><tr>{sortHeader('title', 'Guide')}{sortHeader('retailer', 'Retailer')}{sortHeader('effective_date', 'Document effective date')}{sortHeader('created_at', 'Uploaded')}<th scope="col">Preparation</th><th scope="col"><span className="visually-hidden">Open guide</span></th></tr></thead><tbody>{library.items.map(g => <tr key={g.id}><td><a className="guide-link" href={`#guides/${g.id}`} onClick={() => setNotice('')}><FileText size={17}/><span><strong>{g.title}</strong><small title={g.filename}>{g.version_label || `Edition ${g.edition_number}`} · {g.edition_number} {g.edition_number === 1 ? 'edition' : 'editions'} · {g.page_count === null ? fileSize(g.size_bytes) : `${g.page_count} pages`}</small></span></a></td><td><span className="table-retailer"><RetailerIcon retailer={retailers.find(r => r.id === g.retailer_id) || { name: retailerName(g.retailer_id) }}/>{retailerName(g.retailer_id)}</span></td><td className="table-date">{formatDate(g.effective_date, '—')}</td><td className="table-date">{formatDate(g.created_at)}</td><td><span className={`status-badge ${g.status}`}>{(g.status === 'preparing' || g.status === 'queued') && <LoaderCircle className="spin" size={12}/>}<span className="status-dot"/>{statusNames[g.status]}</span>{g.status === 'preparing' && g.page_count && <small className="table-progress">{g.processed_pages} / {g.page_count} pages</small>}</td><td><button className="icon-button" aria-label={`Open ${g.title}`} onClick={() => openGuide(g.id)}><ChevronRight size={16}/></button></td></tr>)}</tbody></table></div>}
        <div className="pagination library-pagination"><label className="page-size">Rows per page<select aria-label="Rows per page" value={limit} onChange={e => { setLimit(Number(e.target.value)); setOffset(0); }}>{[25, 50, 100].map(n => <option value={n} key={n}>{n}</option>)}</select></label><span className="pagination-range">{library ? `${library.total ? offset + 1 : 0}–${offset + library.items.length} of ${library.total}` : '—'}</span><div><button className="icon-button" aria-label="First page" disabled={!library || page === 1} onClick={() => setOffset(0)}><ChevronsLeft size={16}/></button><button className="icon-button" aria-label="Previous page" disabled={!library || page === 1} onClick={() => setOffset(n => Math.max(0, n - limit))}><ChevronLeft size={16}/></button><label className="page-jump"><span className="visually-hidden">Page</span><select aria-label="Page" value={Math.min(page, pageCount)} disabled={!library || pageCount === 1} onChange={e => setOffset((Number(e.target.value) - 1) * limit)}>{Array.from({ length: pageCount }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}</select><span>of {pageCount}</span></label><button className="icon-button" aria-label="Next page" disabled={!library || page >= pageCount} onClick={() => setOffset(n => n + limit)}><ChevronRight size={16}/></button><button className="icon-button" aria-label="Last page" disabled={!library || page >= pageCount} onClick={() => setOffset((pageCount - 1) * limit)}><ChevronsRight size={16}/></button></div></div>
      </section>
    </>}
  </main><footer className="site-footer"><span className="footer-brand">PARSE by ShipHero</span><span>Policies Analyzed into Rules, Standards &amp; Exceptions</span><span>Created by the Retail Solutions team.</span><span>EDI: Easy. Dependable. Integrated.</span></footer></div>
    {connections && <ConnectionsDialog onClose={() => setConnections(false)}/>}
    {upload && library && <UploadDialog library={library} retailer={retailer} onClose={() => setUpload(false)} onUploaded={uploaded}/>}
  </div>;
}
