import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, ArrowRight, CheckCircle2, LoaderCircle, Play, Settings2 } from 'lucide-react';
import { jsonRequest, useRemote } from './api';
import type { GuideDetail, Run, Workflow } from './api';
import ConnectionsDialog from './ConnectionsDialog';
import ReviewPanel from './ReviewPanel';
import ReleasePanel from './ReleasePanel';
import ScenariosPanel from './ScenariosPanel';
import EditionChanges from './EditionChanges';
import VersionControls, { runLabels } from './VersionControls';

type Tab = 'review' | 'source' | 'analyze' | 'release' | 'scenarios';
export default function WorkflowPanel({guide, source}: {guide: GuideDetail; source: ReactNode}) {
  const data = useRemote<Workflow>(`/api/guides/${guide.id}/workflow`, 4000);
  const draftLink = window.location.hash.match(/\/draft\/([0-9a-f-]{36})$/i)?.[1];
  const [chosenTab, setTab] = useState<Tab | null>(draftLink ? 'review' : null);
  const [runId, setRunId] = useState(draftLink || '');
  const [openedDraft, setOpenedDraft] = useState<Run | null>(null);
  const [provider, setProvider] = useState('anthropic');
  const [model, setModel] = useState('');
  const [batch, setBatch] = useState(12);
  const [connections, setConnections] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [newAnalysis, setNewAnalysis] = useState(false);
  const [ruleEditing, setRuleEditing] = useState(false);
  const [removedIds, setRemovedIds] = useState<string[]>([]);
  const [visited, setVisited] = useState<Tab[]>([]);
  const [actor, setActor] = useState(() => localStorage.getItem('routing-reviewer') || '');
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const deletedIds = new Set([...removedIds, ...(data.data?.deleted_runs || []).map(r=>r.id)]);
  const runs = data.data?.runs.filter(r => !deletedIds.has(r.id)) || [];
  const active = runs.find(r => r.id === runId) || (openedDraft?.id === runId && !deletedIds.has(openedDraft.id) ? openedDraft : null) || runs[0];
  const tab = chosenTab || (active?.payload.rules.length ? 'review' : 'analyze');
  useEffect(() => { setVisited(current => current.includes(tab) ? current : [...current, tab]); }, [tab]);
  // Fix the initial destination after loading; polling must not switch tabs mid-task.
  useEffect(() => { if (data.data && chosenTab === null) setTab(active?.payload.rules.length ? 'review' : 'analyze'); }, [data.data, chosenTab, active]);
  useEffect(() => {
    const followDraft = () => {const id=window.location.hash.match(/\/draft\/([0-9a-f-]{36})$/i)?.[1]; if(id){setRunId(id);setTab('review');}};
    window.addEventListener('hashchange', followDraft); return () => window.removeEventListener('hashchange', followDraft);
  }, []);
  const openDraft = (run: Run) => {
    if (run.guide_id !== guide.id) {window.location.hash=`guides/${run.guide_id}/draft/${run.id}`; return;}
    setOpenedDraft(run); setRunId(run.id); setTab('review'); data.reload();
  };
  const configured = data.data?.connections.find(c => c.id === provider);
  useEffect(() => { setModel(configured?.model || ''); }, [provider, configured?.model]);
  const changeActor = (name: string) => {setActor(name);localStorage.setItem('routing-reviewer',name);};
  const start = async (manual = false) => {
    setBusy(true); setError('');
    try {
      const run = await jsonRequest<Run>(`/api/guides/${guide.id}/analysis`, {provider:manual?'manual':provider, model:manual?'':model, batch_pages:batch, request_id:requestId});
      setRequestId(crypto.randomUUID()); setOpenedDraft(run); setRunId(run.id); setNewAnalysis(false); data.reload(); setTab(manual?'review':'analyze');
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  };
  const control = async (action: string) => {
    if (!active) return;
    setBusy(true); setError('');
    try {await jsonRequest(`/api/analysis/${active.id}/${action}`, {});data.reload();}
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  };
  const running = !!active && ['running','queued'].includes(active.status);
  const checking = ['queued', 'running'].includes(String(active?.payload.assessment_job?.status));
  const checksFailed = active?.payload.assessment_job?.status === 'failed';
  const stopped = !!active && ['failed','cancelled'].includes(active.status);
  const pending = active?.payload.rules.filter(r => r.status === 'pending').length || 0;
  const analysisBlocker = guide.status !== 'ready' ? 'Finish document preparation first.' : data.data?.runs.some(r => ['running','queued'].includes(r.status)) ? 'An analysis is already running.' : !configured?.credential_configured ? 'Connect this provider to start analysis.' : !model.trim() ? 'Enter a model ID.' : !Number.isInteger(batch) || batch < 1 || batch > 50 ? 'Use 1–50 pages per batch.' : '';
  const tabs: [Tab,string,number?][] = [['review','Rules',active?.payload.rules.length],['source','Source',guide.page_count ?? undefined],['analyze','Analysis'],['release','Releases',data.data?.releases.length],['scenarios','Scenarios']];
  return <section className={`workflow guide-workflow ${tab === 'review' ? 'review-active' : ''}`}>
    {data.data && <VersionControls workflow={{...data.data,runs}} active={active} locked={ruleEditing} actor={actor} onActorChange={changeActor}
      onSelect={id=>{setRunId(id);setNewAnalysis(false);setError('');}}
      onDelete={id=>{setRemovedIds(ids=>[...ids,id]);setOpenedDraft(null);setRunId('');setNewAnalysis(false);if(draftLink===id)window.location.hash=`guides/${guide.id}`;data.reload();}}
      onRestore={run=>{setRemovedIds(ids=>ids.filter(id=>id!==run.id));openDraft(run);}}
      onReleases={()=>setTab('release')}/>}
    <nav className="workflow-tabs guide-tabs" aria-label="Guide sections">{tabs.map(([id,label,count]) => <button key={id} aria-current={tab === id ? 'page' : undefined} className={tab === id ? 'selected' : ''} onClick={() => setTab(id)}>{label}{count !== undefined && <span className="guide-tab-count">{count}</span>}{id === 'analyze' && stopped && <span className="tab-attention" aria-label="Analysis stopped"/>}{id === 'analyze' && running && <LoaderCircle size={12} className="spin"/>}</button>)}</nav>
    {(error || data.error) && <div className="error" role="alert"><span>{error || data.error}</span>{data.error && <button onClick={data.reload}>Retry</button>}</div>}
    {(tab === 'source' || visited.includes('source')) && <div className="guide-tab-panel" hidden={tab !== 'source'}>{source}</div>}
    {!data.data && !data.error && tab !== 'source' && <div className="loading"><LoaderCircle size={18} className="spin"/> Loading rules…</div>}
    {data.data && <>
      {tab === 'release' && <div className="guide-context-bar"><label className="release-reviewer">Reviewer<input aria-label="Release reviewer name" value={actor} onChange={e => changeActor(e.target.value)} placeholder="Your name"/></label></div>}
      {active && ['review','analyze'].includes(tab) && (stopped || running) && <div className={`analysis-status-strip ${stopped ? 'stopped' : ''}`} role="status">{running ? <LoaderCircle size={17} className="spin"/> : <AlertCircle size={17}/>}<div><strong>{running ? 'Analysis in progress' : active.status === 'cancelled' ? 'Analysis cancelled' : 'Analysis stopped'}</strong><span>{active.payload.coverage.length} / {guide.page_count ?? '—'} pages · {active.payload.rules.length} rules saved{tab === 'review' ? ' · Read-only until analysis completes' : ''}</span></div><div className="analysis-status-actions">{stopped && <button className="secondary" disabled={busy || guide.status !== 'ready'} onClick={() => control('retry')}><Play size={13}/> Resume analysis</button>}{running && <button className="secondary" disabled={busy} onClick={() => control('cancel')}>Stop</button>}{tab !== 'analyze' && <button className="text-button" onClick={() => setTab('analyze')}>Details <ArrowRight size={13}/></button>}</div></div>}
      {tab === 'review' && active?.status === 'published' && <div className="published-status-strip"><CheckCircle2 size={16}/><span>Published · Read-only</span><button className="text-button" onClick={() => setTab('release')}>Create an editable draft <ArrowRight size={13}/></button></div>}
      {tab === 'review' && active && guide.previous_guide_id && <EditionChanges run={active}/>}
      {(tab === 'review' || visited.includes('review')) && <div className="guide-tab-panel" hidden={tab !== 'review'}>{active ? <ReviewPanel key={active.id} run={active} onEditingChange={setRuleEditing} connections={data.data.connections} actor={actor} onActorChange={changeActor} reload={data.reload}/> : <div className="guide-empty"><h2>No rules yet</h2><button className="primary" onClick={() => setTab('analyze')}>Set up analysis <ArrowRight size={15}/></button></div>}</div>}
      {tab === 'analyze' && <div className="analysis-panel compact-analysis">
        {active && <section className="analysis-summary"><div className="section-heading"><h2>{checking ? active.payload.assessment_job?.phase === 'resolve' ? 'Preparing rules' : 'Checking rules' : runLabels[active.status] || active.status}</h2><span className="muted">{String(active.config.model || 'Manual review')}</span></div><div className="analysis-metrics"><div><strong>{active.payload.coverage.length}<small> / {guide.page_count ?? '—'}</small></strong><span>Pages examined</span></div><div><strong>{active.payload.rules.length}</strong><span>Rules saved</span></div><div><strong>{pending}</strong><span>Pending review</span></div></div>{checking && <p role="status">{active.payload.assessment_job?.phase === 'resolve' ? 'Resolving supported rule details' : 'Checking accuracy and duplicates'}: {String(active.payload.assessment_job?.phase === 'resolve' ? active.payload.assessment_job?.prepared : active.payload.assessment_job?.processed)} of {String(active.payload.assessment_job?.total)} rules.</p>}{checksFailed && <p role="status">Rules are saved, but readiness checks need attention. Open Rules to continue.</p>}<progress aria-label="Pages examined" value={active.payload.coverage.length} max={guide.page_count || 1}/>{active.error && <div className="analysis-error-detail"><strong>Why analysis stopped</strong><p>{active.error}</p>{!!active.payload.pending_batches.length && <p>Pages remaining: {active.payload.pending_batches.flat().sort((a,b) => a-b).join(', ')}</p>}</div>}<div className="action-row">{!!active.payload.rules.length && <button className="primary" onClick={() => setTab('review')}>{active.status === 'complete' ? 'Review rules' : 'View saved rules'} <ArrowRight size={14}/></button>}<button className="secondary" disabled={running || busy} onClick={() => setNewAnalysis(v => !v)}>{newAnalysis ? 'Close setup' : 'New analysis'}</button></div><details className="analysis-record"><summary>Run details</summary><dl><div><dt>Started</dt><dd>{new Date(active.created_at).toLocaleString()}</dd></div><div><dt>Model</dt><dd>{String(active.config.model || 'Manual')}</dd></div><div><dt>Prompt</dt><dd>{String(active.config.prompt_version || '—')}</dd></div></dl><div className="analysis-batches"><table><thead><tr><th>Batch</th><th>PDF pages</th><th>Model</th><th>Details</th></tr></thead><tbody>{active.payload.batches.map((b,i) => <tr key={i}><td>{i+1}</td><td>{Array.isArray(b.pages) ? b.pages.join(', ') : '—'}</td><td>{String(b.model)}</td><td><details><summary>Usage & prompt</summary><pre>{JSON.stringify({prompt:b.prompt_version || active.config.prompt_version,usage:b.usage},null,2)}</pre></details></td></tr>)}</tbody></table></div></details></section>}
        {!!active?.payload.warnings.length && <details className="analysis-record"><summary>Review notices ({active.payload.warnings.length})</summary><ul>{active.payload.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
        {(!active || newAnalysis) && <section className="analysis-setup"><div className="section-heading"><h2>{active ? 'New analysis' : 'Analyze guide'}</h2><button className="secondary" onClick={() => setConnections(true)}><Settings2 size={14}/> Connections</button></div><div className="analysis-options"><label>Provider<select value={provider} onChange={e => setProvider(e.target.value)}><option value="anthropic">Claude / Anthropic</option><option value="openai">OpenAI</option></select></label><label>Model<input value={model} onChange={e => setModel(e.target.value)} placeholder="Model ID"/></label></div><details className="analysis-advanced"><summary>Advanced settings</summary><label>Pages per batch<input type="number" min={1} max={50} value={batch} onChange={e => setBatch(Number(e.target.value))}/></label></details><p className="analysis-disclosure">Sends guide text and page images to {provider === 'anthropic' ? 'Anthropic' : 'OpenAI'}. Includes automatic readiness and duplicate checks after extraction. Usage charges apply.</p>{analysisBlocker && <p className="analysis-blocker">{analysisBlocker}{!configured?.credential_configured && <button className="text-button" onClick={() => setConnections(true)}>Open Connections</button>}</p>}<div className="action-row"><button className="primary" disabled={busy || !!analysisBlocker} onClick={() => start()}><Play size={14}/> {busy ? 'Starting…' : 'Start analysis'}</button><button className="secondary" disabled={busy || guide.status !== 'ready'} onClick={() => start(true)}>Create manual draft</button></div></section>}
      </div>}
      {(tab === 'release' || visited.includes('release')) && <div className="guide-tab-panel" hidden={tab !== 'release'}><ReleasePanel guideId={guide.id} key={`${active?.id}:${active?.version}:${data.data.active_release_id}`} run={active} releases={data.data.releases} activeId={data.data.active_release_id} actor={actor} reload={data.reload} onDraft={openDraft}/></div>}
      {(tab === 'scenarios' || visited.includes('scenarios')) && <div className="guide-tab-panel" hidden={tab !== 'scenarios'}><ScenariosPanel retailerId={guide.retailer_id} releases={data.data.releases} activeId={data.data.active_release_id}/></div>}
    </>}
    {connections && <ConnectionsDialog onClose={() => {setConnections(false);data.reload();}}/>}
  </section>;
}
