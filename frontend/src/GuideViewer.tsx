import { useEffect, useState } from 'react';
import { AlertCircle, ArrowLeft, ChevronLeft, ChevronRight, Download, FileText, LoaderCircle, RefreshCw, ScanText, ZoomIn, ZoomOut } from 'lucide-react';
import { fileSize, formatDate, request, statusNames, useRemote } from './api';
import type { GuideDetail, PageDetail } from './api';

export default function GuideViewer({ guideId, retailerName, onBack, notice }: {
  guideId: string; retailerName: (id: string) => string; onBack: () => void; notice: string;
}) {
  const { data: guide, error, reload } = useRemote<GuideDetail>(`/api/guides/${guideId}`, 4000);
  const [index, setIndex] = useState(0);
  const [zoom, setZoom] = useState(100);
  const [showText, setShowText] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [actionError, setActionError] = useState('');
  const [imageError, setImageError] = useState(false);
  const pageSummary = guide?.pages[index];
  const pageRevision = `${pageSummary?.text_status ?? ''}:${pageSummary?.image_status ?? ''}`;
  const page = useRemote<PageDetail>(`/api/guides/${guideId}/pages/${index}?revision=${encodeURIComponent(pageRevision)}`);
  useEffect(() => { setImageError(false); }, [guideId, index, pageSummary?.image_status]);
  const retry = async () => {
    setRetrying(true); setActionError('');
    try { await request(`/api/guides/${guideId}/retry`, { method: 'POST' }); reload(); }
    catch (e) { setActionError(e instanceof Error ? e.message : 'Unable to retry.'); }
    finally { setRetrying(false); }
  };
  return <>
    <button className="back-link" onClick={onBack}><ArrowLeft size={16}/> Back to guides</button>
    {notice && <div className="notice" role="status">{notice}</div>}
    {error && <div className="error" role="alert"><AlertCircle size={18}/><span>{error}</span><button onClick={reload}>Retry</button></div>}
    {!guide && !error && <div className="loading"><LoaderCircle className="spin" size={20}/> Opening guide…</div>}
    {guide && <>
      <div className="page-heading document-heading"><div><span className="eyebrow">{retailerName(guide.retailer_id)}</span><h1>{guide.title}</h1><p>{guide.version_label || 'Version not specified'}<span className="separator">·</span>Effective {formatDate(guide.effective_date, 'date not specified')}</p></div><a className="secondary" href={`/api/guides/${guide.id}/original`}><Download size={16}/> Original PDF</a></div>
      <div className="document-meta"><span className={`status-badge ${guide.status}`}>{statusNames[guide.status]}</span><span>{guide.page_count === null ? 'Counting pages' : `${guide.page_count} pages`}</span><span>{fileSize(guide.size_bytes)}</span><span>Uploaded {formatDate(guide.created_at)}</span></div>
      {(guide.status === 'queued' || guide.status === 'preparing') && <div className="preparing-banner" role="status"><LoaderCircle size={19} className="spin"/><div><strong>{guide.status === 'queued' ? 'Your guide is waiting to be prepared' : 'Preparing your guide'}</strong><p>{guide.page_count ? `${guide.processed_pages} of ${guide.page_count} pages processed. You can view completed pages below.` : 'We’ll preserve the original and prepare a preview and text for each page.'}</p></div></div>}
      {(guide.error || guide.attention_pages > 0) && <div className="attention-banner"><AlertCircle size={19}/><div><strong>{guide.error || `${guide.attention_pages} ${guide.attention_pages === 1 ? 'page needs' : 'pages need'} attention`}</strong>{!guide.error && <p>Some page previews or text extraction failed. Select a marked page to inspect it, or retry preparation.</p>}</div>{guide.can_retry && <button className="secondary" onClick={retry} disabled={retrying}><RefreshCw size={15}/> {retrying ? 'Retrying…' : 'Retry preparation'}</button>}</div>}
      {actionError && <div className="error" role="alert">{actionError}</div>}
      {guide.status === 'ready' && <section className="next-step" aria-labelledby="next-step-heading"><span className="eyebrow">NEXT STEP</span><h2 id="next-step-heading">Analyze the guide’s rules</h2><p>Your pages are ready. AI analysis will use text and page images to propose requirements with source references. You’ll review the proposals before approving rules for instructions and scenario checks.</p><p className="next-step-availability">AI analysis isn’t available yet. For now, you can inspect the prepared pages below.</p></section>}
      <section className="viewer" aria-label="Guide pages"><div className="viewer-toolbar"><div className="page-controls"><button className="icon-button" aria-label="Previous page" disabled={!index} onClick={() => setIndex(i => i - 1)}><ChevronLeft size={19}/></button><label className="page-select">Page <select aria-label="Page number" value={index} disabled={!guide.pages.length} onChange={e => setIndex(Number(e.target.value))}>{guide.pages.length ? guide.pages.map(p => <option key={p.page_index} value={p.page_index}>{p.page_index + 1}{p.issue ? ' · needs attention' : ''}</option>) : <option value={0}>—</option>}</select><span>of {guide.page_count ?? '—'}</span></label><button className="icon-button" aria-label="Next page" disabled={index + 1 >= guide.pages.length} onClick={() => setIndex(i => i + 1)}><ChevronRight size={19}/></button></div><div className="viewer-actions"><button className="icon-button" aria-label="Zoom out" onClick={() => setZoom(v => Math.max(75, v - 25))} disabled={zoom <= 75}><ZoomOut size={17}/></button><span>{zoom}%</span><button className="icon-button" aria-label="Zoom in" onClick={() => setZoom(v => Math.min(200, v + 25))} disabled={zoom >= 200}><ZoomIn size={17}/></button><button className={`text-toggle ${showText ? 'selected' : ''}`} aria-pressed={showText} onClick={() => setShowText(v => !v)}><ScanText size={17}/> Text</button></div></div>
        <div className={`viewer-body ${showText ? '' : 'image-only'}`}><div className="page-canvas">{pageSummary?.image_status === 'ready' && !imageError ? <img className="source-page" style={{ width: `${zoom}%` }} src={`/api/guides/${guideId}/pages/${index}/image`} alt={`Original PDF page ${index + 1} of ${guide.title}`} onError={() => setImageError(true)}/> : <div className="page-placeholder"><FileText size={38}/><h3>{pageSummary?.image_status === 'failed' || imageError ? 'Preview unavailable' : 'Your page preview will appear here'}</h3><p>{pageSummary?.image_status === 'failed' || imageError ? 'You can download the original PDF above.' : 'Pages become available as preparation finishes.'}</p></div>}</div>
          {showText && <aside className="text-pane"><div className="text-pane-heading"><ScanText size={16}/><h2>Extracted text</h2></div><p className="text-explainer">Check the original page for layout, tables and diagrams.</p>{pageSummary?.issue && <div className="page-issue"><AlertCircle size={15}/>{pageSummary.issue}</div>}{pageSummary && page.error ? <div className="error" role="alert">{page.error}<button onClick={page.reload}>Retry</button></div> : page.data?.text ? <pre>{page.data.text}</pre> : <div className="text-empty">{pageSummary?.text_status === 'no_text' ? 'This page has no embedded text. Its image is preserved for visual analysis, including any labels, diagrams or requirements.' : pageSummary?.text_status === 'failed' ? 'Text extraction failed for this page.' : 'Text will appear once this page is prepared.'}</div>}</aside>}
        </div><div className="viewer-caption">Page numbers refer to PDF pages and may differ from printed page labels. Original document preserved.</div>
      </section><p className="document-footnote">Document preparation does not extract or approve rules. AI rule analysis is not available yet.</p>
    </>}
  </>;
}
