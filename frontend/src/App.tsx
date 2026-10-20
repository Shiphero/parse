import { useEffect, useState } from 'react';
import { AlertCircle, ArrowRight, BookOpen, ChevronLeft, ChevronRight, FileText, FolderOpen, HelpCircle, LoaderCircle, Plus, Search, Settings2, ShieldCheck, Upload, X } from 'lucide-react';
import { fileSize, formatDate, statusNames, useRemote } from './api';
import type { Library, UploadResult } from './api';
import ParseBrand from './ParseBrand';
import GuideViewer from './GuideViewer';
import UploadDialog from './UploadDialog';
import ConnectionsDialog from './ConnectionsDialog';

function selectedGuide() { return window.location.hash.match(/^#guides\/([0-9a-f-]{36})(?:\/draft\/[0-9a-f-]{36})?$/i)?.[1] ?? null; }

export default function App() {
  const [retailer, setRetailer] = useState('');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [offset, setOffset] = useState(0);
  const [upload, setUpload] = useState(false);
  const [revision, setRevision] = useState(0);
  const [guideId, setGuideId] = useState(selectedGuide);
  const [notice, setNotice] = useState('');
  const [help, setHelp] = useState(false);
  const [connections, setConnections] = useState(false);
  useEffect(() => { const t = window.setTimeout(() => setQuery(search), 250); return () => window.clearTimeout(t); }, [search]);
  useEffect(() => { const listener = () => { setGuideId(selectedGuide()); }; window.addEventListener('hashchange', listener); return () => window.removeEventListener('hashchange', listener); }, []);
  const params = new URLSearchParams({ q: query, offset: String(offset), limit: '30' });
  if (retailer) params.set('retailer_id', retailer);
  if (status) params.set('status', status);
  const { data: library, error, reload } = useRemote<Library>(`/api/guides?${params}`, 5000, revision);
  const [retailers, setRetailers] = useState<Library['retailers']>([]);
  useEffect(() => { if (library) setRetailers(library.retailers); }, [library]);
  const retailerName = (id: string) => retailers.find(r => r.id === id)?.name || id;
  const totalGuides = retailers.reduce((sum, r) => sum + r.guide_count, 0);
  const selectRetailer = (id: string) => { setRetailer(id); setOffset(0); setNotice(''); window.location.hash = 'guides'; };
  const openGuide = (id: string) => { window.location.hash = `guides/${id}`; };
  const uploaded = (result: UploadResult) => {
    setUpload(false); setRevision(n => n + 1);
    setNotice(result.existing ? 'This file is already in your library. We opened the existing guide.' : 'Guide uploaded. Your original PDF is saved; page preparation will continue in the background.');
    openGuide(result.guide.id);
  };
  const filtersActive = Boolean(search || status);
  return <div className="shell"><aside className="sidebar">
    <a className="brand" aria-label="PARSE by ShipHero — guide library" href="#guides" onClick={() => selectRetailer('')}><ParseBrand/></a>
    <div className="nav-section-label">WORKSPACE</div><nav aria-label="Guide library"><button className={`nav-item ${!retailer ? 'active' : ''}`} onClick={() => selectRetailer('')} aria-current={!retailer ? 'page' : undefined}><BookOpen size={18}/> All guides <span className="nav-count">{totalGuides}</span></button><div className="nav-section-label retailer-nav-label">RETAILERS</div>{retailers.map(r => <button key={r.id} className={`nav-item retailer-nav ${retailer === r.id ? 'active' : ''}`} onClick={() => selectRetailer(r.id)} aria-current={retailer === r.id ? 'page' : undefined}><span className={`retailer-dot ${r.id}`}/>{r.name}<span className="nav-count">{r.guide_count}</span></button>)}<button className="nav-item" onClick={() => setConnections(true)}><Settings2 size={18}/> Connections</button></nav>
    <div className="sidebar-bottom"><button className="help-button" onClick={() => setHelp(v => !v)} aria-expanded={help}><HelpCircle size={17}/> Working with guides</button>{help && <p>Upload the original PDF for each version. Use the effective date from the guide, then inspect its pages and any preparation issues. Existing files are preserved when you add another version.</p>}<div className="private-label"><ShieldCheck size={13}/> Internal workspace</div></div>
  </aside><div className="main-wrap"><header className="topbar"><span><FolderOpen size={15}/> Library <ChevronRight size={13}/><strong>{guideId ? 'Guide details' : retailer ? retailerName(retailer) : 'All guides'}</strong></span><span className="topbar-note">From retailer requirements to operational rules</span></header><main>
    {guideId ? <GuideViewer key={guideId} guideId={guideId} retailerName={retailerName} onBack={() => { setNotice(''); window.location.hash = 'guides'; }} notice={notice}/> : <>
      <div className="page-heading"><div><h1>{retailer ? retailerName(retailer) : 'Routing guides'}</h1><p>Turn retailer guides into reviewed rules, clear instructions and shipment checks.</p></div><button className="primary" onClick={() => setUpload(true)} disabled={!library}><Plus size={18}/> Upload guide</button></div>
      {!retailer && retailers.length > 0 && <div className="retailer-strip" aria-label="Filter by retailer">{retailers.map(r => <button className="retailer-card" key={r.id} onClick={() => selectRetailer(r.id)}><span className={`retailer-mark ${r.id}`}>{r.name[0]}</span><span><strong>{r.name}</strong><small>{r.guide_count} {r.guide_count === 1 ? 'guide' : 'guides'}</small></span><ChevronRight size={15}/></button>)}</div>}
      <section className="library-panel" aria-label="Routing guide library"><div className="library-toolbar"><div className="search-field"><Search size={17}/><input aria-label="Search guides" placeholder="Search guides…" value={search} onChange={e => { setSearch(e.target.value); setOffset(0); }}/>{search && <button className="icon-button" aria-label="Clear search" onClick={() => { setSearch(''); setOffset(0); }}><X size={14}/></button>}</div><select className="status-filter" aria-label="Filter by preparation status" value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}><option value="">All statuses</option>{Object.entries(statusNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="result-count">{library ? `${library.total} ${library.total === 1 ? 'guide' : 'guides'}` : 'Loading…'}</span></div>
      {error && <div className="error library-error" role="alert"><AlertCircle size={18}/><span>{error}{library ? ' Showing the last available results.' : ''}</span><button onClick={reload}>Retry</button></div>}
      {!library && !error && <div className="loading"><LoaderCircle className="spin" size={20}/> Loading your guides…</div>}
      {library && library.items.length === 0 && <div className="empty-library">{filtersActive ? <><span className="empty-search"><Search size={30}/></span><h2>No guides match these filters</h2><p>Try another title or clear the filters to see all {retailer ? retailerName(retailer) : 'your'} guides.</p><button className="secondary" onClick={() => { setSearch(''); setStatus(''); setOffset(0); }}>Clear filters</button></> : <><span className="empty-document" aria-hidden="true"><FileText size={28}/></span><h2>{retailer ? `Add a guide for ${retailerName(retailer)}` : 'Add your first routing guide'}</h2><p>Upload a retailer’s original PDF. Keep versions together and inspect every page alongside its extracted text.</p><button className="primary" onClick={() => setUpload(true)}><Upload size={17}/> Upload guide</button><span className="upload-caption">Original PDFs preserved · No changes to retailer requirements</span></>}</div>}
      {library && library.items.length > 0 && <><div className="guide-table-wrap"><table className="guide-table"><thead><tr><th>Guide</th><th>Retailer</th><th>Effective date</th><th>Preparation</th><th><span className="visually-hidden">Open guide</span></th></tr></thead><tbody>{library.items.map(g => <tr key={g.id}><td><button className="guide-link" onClick={() => { setNotice(''); openGuide(g.id); }}><span className="guide-file-icon"><FileText size={22}/></span><span><strong>{g.title}</strong><small>{g.version_label || g.filename} · {g.page_count === null ? fileSize(g.size_bytes) : `${g.page_count} pages`}</small></span></button></td><td>{retailerName(g.retailer_id)}</td><td>{formatDate(g.effective_date)}</td><td><span className={`status-badge ${g.status}`}>{(g.status === 'preparing' || g.status === 'queued') && <LoaderCircle size={12} className="spin"/>}{statusNames[g.status]}</span>{g.status === 'preparing' && g.page_count && <small className="table-progress">{g.processed_pages} of {g.page_count} pages</small>}</td><td><button className="icon-button" aria-label={`Open ${g.title}`} onClick={() => { setNotice(''); openGuide(g.id); }}><ChevronRight size={18}/></button></td></tr>)}</tbody></table></div><div className="pagination"><span>Showing {library.offset + 1}–{library.offset + library.items.length} of {library.total}</span><div><button className="icon-button" aria-label="Previous results" disabled={offset === 0} onClick={() => setOffset(n => Math.max(0, n - 30))}><ChevronLeft size={17}/></button><button className="icon-button" aria-label="Next results" disabled={offset + library.items.length >= library.total} onClick={() => setOffset(n => n + 30)}><ChevronRight size={17}/></button></div></div></>}
      </section><div className="library-footer"><ShieldCheck size={15}/><span>Each upload keeps its original document. Adding a new version never replaces an earlier guide.</span><button className="text-button" onClick={() => setHelp(true)}>About your library <ArrowRight size={14}/></button></div>
    </>}
  </main><footer className="site-footer"><span className="footer-brand">PARSE by ShipHero</span><span>Policies Analyzed into Rules, Standards &amp; Exceptions</span><span>Created by the Retail Solutions team.</span><span>EDI: Easy. Dependable. Integrated.</span></footer></div>{connections && <ConnectionsDialog onClose={() => setConnections(false)}/>} {upload && library && <UploadDialog library={library} retailer={retailer} onClose={() => setUpload(false)} onUploaded={uploaded}/>}</div>;
}
