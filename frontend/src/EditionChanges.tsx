import { useRemote } from './api';
import type { Candidate, RuleSpec, Run } from './api';
import { Evidence } from './RuleEditor';

type Previous = {stable_id:string;spec:RuleSpec;source_guide_id:string};
type Diff = {available:boolean;reason?:string;previous_guide_id?:string;previous_label?:string;partial?:boolean;previous_rules?:Previous[];current_rules?:Candidate[];unchanged?:Record<string,string>;changed?:Record<string,string[]>;added?:string[];missing?:string[]};
export default function EditionChanges({run}: {run:Run}) {
  const data=useRemote<Diff>(`/api/analysis/${run.id}/edition-comparison`,0,run.version);
  const diff=data.data;
  if(data.error) return <div className="error">Edition comparison unavailable. <button onClick={data.reload}>Retry</button></div>;
  if(!diff) return <p className="muted">Loading edition comparison…</p>;
  return <details className="edition-changes"><summary>Changes from {diff.previous_label || 'previous edition'}{diff.available ? ` · ${Object.keys(diff.unchanged||{}).length} unchanged · ${Object.keys(diff.changed||{}).length} possible changes · ${diff.added?.length || 0} added · ${diff.missing?.length || 0} not found` : ''}</summary>
    {!diff.available ? <p>{diff.reason}</p> : <>
      {diff.partial && <p className="notice">Partial analysis. Counts are provisional; rules not found may appear in later batches.</p>}
      <p className="muted">Matching titles suggest a change. Source page changes do not count as rule-content changes. Approval still requires source review.</p>
      {Object.entries(diff.changed||{}).map(([id,ids])=>{const previous=diff.previous_rules!.find(r=>r.stable_id===id)!;return <article key={id}><strong>{previous.spec.title}</strong><div className="edition-change-pair"><div><h4>Previous edition</h4><p>{previous.spec.instruction}</p><details><summary>Previous evidence</summary><Evidence guideId={previous.source_guide_id} spec={previous.spec}/></details></div><div><h4>This edition</h4>{ids.map(rid=>{const current=diff.current_rules!.find(r=>r.id===rid)!;return <div key={rid}><p>{current.spec.instruction}</p><details><summary>Current evidence</summary><Evidence guideId={current.source_guide_id} spec={current.spec}/></details></div>;})}</div></div></article>;})}
      <details><summary>Added · {diff.added?.length || 0}</summary>{diff.added?.map(id=>{const rule=diff.current_rules!.find(r=>r.id===id)!;return <article key={id}><strong>{rule.spec.title}</strong><p>{rule.spec.instruction}</p></article>;})}</details>
      <details><summary>Not found in this edition · {diff.missing?.length || 0}</summary>{diff.missing?.map(id=>{const rule=diff.previous_rules!.find(r=>r.stable_id===id)!;return <article key={id}><strong>{rule.spec.title}</strong><p>{rule.spec.instruction}</p></article>;})}</details>
    </>}{diff.previous_guide_id&&<a href={`#guides/${diff.previous_guide_id}`}>Open previous document edition</a>}
  </details>;
}
