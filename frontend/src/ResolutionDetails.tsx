import type { Candidate, RuleSpec } from './api';

const labels: Record<string, string> = {instruction:'Instruction', title:'Title', purpose:'Rule use',
  operational_category:'Category', consumption_points:'Used in', rule_type:'Rule type', placements:'Workflow placement',
  standard_check:'Verification check', verification:'Verification method', applicability_text:'When it applies',
  applicability:'Conditions', exceptions:'Exceptions', unresolved_questions:'Unresolved questions',
  execution_mode:'Automatic verification', evidence:'Source evidence', check_id:'Check', id:'Type',
  reference_only:'Reference requirement', standard:'Standard verification', field:'Field'};
const words = (value:string) => labels[value] || value.replaceAll('_',' ').replaceAll('.',' / ');
function Value({value, names}: {value:unknown; names:Record<string,string>}) {
  if (value == null || value === '') return <span className="muted">Not set</span>;
  if (typeof value === 'boolean') return <>{value ? 'Yes' : 'No'}</>;
  if (typeof value !== 'object') return <>{typeof value === 'string' ? names[value] || labels[value] || value : String(value)}</>;
  if (Array.isArray(value)) return value.length ? <ul>{value.map((item,i)=><li key={i}><Value value={item} names={names}/></li>)}</ul> : <span className="muted">None</span>;
  return <dl>{Object.entries(value).map(([key,item])=><div key={key}><dt>{words(key)}</dt><dd><Value value={item} names={names}/></dd></div>)}</dl>;
}
export default function ResolutionDetails({candidate, dirty, disabled, onUse, names}: {
  candidate:Candidate; dirty:boolean; disabled:boolean; onUse:(spec:RuleSpec)=>void; names:Record<string,string>;
}) {
  const record = candidate.resolution;
  const changes = record?.changes || [];
  if (!record || !changes.length) return null;
  const stale = dirty || record.revision !== candidate.revision;
  const proposed = changes.filter(change=>!change.applied);
  const useChanges = () => onUse({...candidate.spec, ...Object.fromEntries(proposed.map(c=>[c.field,c.after]))} as RuleSpec);
  return <section className="resolution-details" aria-label="Rule improvements">
    <h3>{stale ? 'Previous rule improvements' : proposed.length ? 'Proposed corrections' : 'Automatically resolved'}</h3>
    {stale && <p>The rule has changed. Run the checks again before using these proposals.</p>}
    {changes.map(change=><details key={change.field} open={!change.applied && !stale}>
      <summary>{words(change.field)} · {change.applied ? 'Applied' : change.verified ? 'Source verified · needs your confirmation' : 'Needs confirmation'}</summary>
      <p>{change.explanation}</p>
      <div className="resolution-comparison"><div><strong>Before</strong><Value value={change.before} names={names}/></div><div><strong>{change.applied ? 'Updated' : 'Proposed'}</strong><Value value={change.after} names={names}/></div></div>
      {change.sources.map((source,i)=><blockquote key={i}>{source.quote} <a href={`/api/guides/${candidate.source_guide_id}/original#page=${source.page}`} target="_blank" rel="noreferrer">PDF page {source.page}</a></blockquote>)}
    </details>)}
    {!!proposed.length && !stale && <button type="button" className="secondary" disabled={disabled} onClick={useChanges}>Use proposed changes in editor</button>}
    {!!proposed.length && !stale && <p className="muted">Review the proposed values and save to apply them.</p>}
  </section>;
}
