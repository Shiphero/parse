import { useEffect, useState } from 'react';
import { AlertCircle, ChevronLeft, ChevronRight, FileText, ScanText, ZoomIn, ZoomOut } from 'lucide-react';
import { useRemote } from './api';
import type { GuideDetail, PageDetail } from './api';

export default function GuideSource({guide}: {guide: GuideDetail}) {
  const [index, setIndex] = useState(0);
  const [pageInput, setPageInput] = useState('1');
  const [zoom, setZoom] = useState(100);
  const [showText, setShowText] = useState(false);
  const [imageError, setImageError] = useState(false);
  const summary = guide.pages[index];
  const revision = `${summary?.text_status ?? ''}:${summary?.image_status ?? ''}`;
  const page = useRemote<PageDetail>(`/api/guides/${guide.id}/pages/${index}?revision=${encodeURIComponent(revision)}`);
  useEffect(() => { setPageInput(String(index + 1)); setImageError(false); }, [index, summary?.image_status]);
  const jump = () => {
    const target = Number(pageInput);
    if (Number.isInteger(target) && target >= 1 && target <= guide.pages.length) setIndex(target - 1);
    else setPageInput(String(index + 1));
  };
  const issues = guide.pages.filter(p => p.issue);
  return <section className="viewer guide-source" aria-label="Source document">
    <div className="viewer-toolbar"><div className="page-controls">
      <button className="icon-button" aria-label="Previous source page" disabled={!index} onClick={() => setIndex(i => i - 1)}><ChevronLeft size={18}/></button>
      <form className="source-page-jump" onSubmit={e => {e.preventDefault(); jump();}}><label htmlFor="source-page-number">Page</label><input id="source-page-number" aria-label="Source page number" type="number" min={1} max={Math.max(1, guide.pages.length)} value={pageInput} disabled={!guide.pages.length} onChange={e => setPageInput(e.target.value)} onBlur={jump}/><span>/ {guide.page_count ?? '—'}</span><button type="submit" className="text-button" disabled={!guide.pages.length}>Go</button></form>
      <button className="icon-button" aria-label="Next source page" disabled={index + 1 >= guide.pages.length} onClick={() => setIndex(i => i + 1)}><ChevronRight size={18}/></button>
    </div>{issues.length > 0 && <select aria-label="Pages needing attention" className="source-issue-select" value="" onChange={e => setIndex(Number(e.target.value))}><option value="" disabled>{issues.length} pages need attention</option>{issues.map(p => <option key={p.page_index} value={p.page_index}>Page {p.page_index + 1}</option>)}</select>}
    <div className="viewer-actions"><button className="icon-button" aria-label="Zoom out" onClick={() => setZoom(v => Math.max(75, v - 25))} disabled={zoom <= 75}><ZoomOut size={16}/></button><span>{zoom}%</span><button className="icon-button" aria-label="Zoom in" onClick={() => setZoom(v => Math.min(200, v + 25))} disabled={zoom >= 200}><ZoomIn size={16}/></button><button className={`text-toggle ${showText ? 'selected' : ''}`} aria-pressed={showText} onClick={() => setShowText(v => !v)}><ScanText size={16}/> Text</button></div></div>
    <div className={`viewer-body ${showText ? '' : 'image-only'}`}><div className="page-canvas">
      {summary?.image_status === 'ready' && !imageError ? <img className="source-page" style={{width:`${zoom}%`}} src={`/api/guides/${guide.id}/pages/${index}/image`} alt={`PDF page ${index + 1} of ${guide.title}`} onError={() => setImageError(true)}/> : <div className="page-placeholder"><FileText size={28}/><h3>{summary?.image_status === 'failed' || imageError ? 'Preview unavailable' : 'Preparing page…'}</h3><a href={`/api/guides/${guide.id}/original`}>Open original PDF</a></div>}
    </div>{showText && <aside className="text-pane"><div className="text-pane-heading"><ScanText size={16}/><h2>Extracted text</h2></div>{summary?.issue && <div className="page-issue"><AlertCircle size={15}/>{summary.issue}</div>}{summary && page.error ? <div className="error" role="alert">{page.error}<button onClick={page.reload}>Retry</button></div> : page.data?.text ? <pre>{page.data.text}</pre> : <div className="text-empty">{summary?.text_status === 'no_text' ? 'No embedded text. Refer to the page image.' : summary?.text_status === 'failed' ? 'Text extraction failed.' : 'Preparing text…'}</div>}</aside>}</div>
    <div className="viewer-caption">PDF page {index + 1} · Printed page numbers may differ.</div>
  </section>;
}
