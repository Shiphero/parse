import type { Candidate } from './api';
import type { ReviewSection } from './reviewReadiness';
import { assessmentLabels } from './assessmentReadiness';

const duplicateLabels = {duplicate: 'Likely duplicate', distinct: 'Separate requirement', conflict: 'Conflicting requirement', uncertain: 'Uncertain match'};
const sections: Record<string, string> = {instruction: 'Review instruction', classification: 'Review classification',
  conditions: 'Review conditions', verification: 'Review verification', evidence: 'Review source', advanced: 'Resolve questions'};
export default function AssessmentDetails({candidate, dirty, goTo, onOpenRelated}: {
  candidate: Candidate; dirty: boolean; goTo: (section: ReviewSection) => void; onOpenRelated?: (id: string) => void;
}) {
  const assessment = candidate.assessment;
  if (!assessment) return null;
  const stale = dirty || candidate.assessment_stale;
  return <section className={`assessment-detail ${stale ? 'stale' : assessment.outcome}`} aria-label="Rule assessment">
    <h3>Jev assessment · {stale ? 'Reassessment needed' : assessmentLabels[assessment.outcome]}</h3>
    {stale ? <p>This rule or a matching proposal changed. Save any edits and reassess before relying on this recommendation.</p> : <>
      {assessment.outcome === 'ready' ? <p>No issue was identified in the assessed text or application checks. This preview has not approved the rule.</p>
        : <><strong>What needs attention</strong><ul>{assessment.issues.map((issue, i) => <li key={i}>
          <p>{issue.action}</p><div className="action-row"><button className="text-button" onClick={() => goTo(issue.section)}>{sections[issue.section]} →</button>
            {onOpenRelated && (issue.related_rule_ids || []).map((id, index) => <button className="text-button" key={id} onClick={() => onOpenRelated(id)}>Open matching rule {index + 1} →</button>)}
          </div></li>)}</ul></>}
    </>}
    {!!assessment.duplicates?.length && <div className="assessment-duplicates"><strong>{stale ? 'Previous duplicate comparisons' : 'Duplicate comparisons'}</strong>
      <p>Compared {assessment.duplicates.length} of {assessment.duplicate_candidates} likely matches.</p>
      <ul>{assessment.duplicates.map(match => <li key={match.rule_id}><strong>{duplicateLabels[match.choice]}</strong> · {match.title}
        <span className="muted"> · PDF pages {match.source_pages.join(', ')} · {Math.round(Math.min(match.confidence, match.probabilities[match.choice]) * 100)}% model confidence</span>
        {!stale && onOpenRelated && <button className="text-button" onClick={() => onOpenRelated(match.rule_id)}>Open compared rule →</button>}
      </li>)}</ul>
    </div>}
    <details><summary>{stale ? 'Previous assessment details' : 'Assessment details'}</summary>
      <p>{assessment.model} · {new Date(assessment.assessed_at).toLocaleString()} · rule revision {assessment.revision}</p>
      <p>Source context: PDF pages {assessment.source_pages.join(', ') || 'unavailable'}. Duplicate comparison checks likely matches across titles; it is not an exhaustive search.</p>
      <p>Preview confidence threshold: {Math.round(assessment.threshold * 100)}%. Model confidence is not measured accuracy.</p>
      {assessment.dimensions.length ? <table><thead><tr><th>Check</th><th>Assessment</th><th>Confidence</th></tr></thead><tbody>{assessment.dimensions.map(d => <tr key={d.name}>
        <td>{d.name.replaceAll('_', ' ')}</td><td>{d.choice.replaceAll('_', ' ')}</td><td>{Math.round(Math.min(d.confidence, d.probabilities[d.choice]) * 100)}%</td>
      </tr>)}</tbody></table> : <p>Jev was not called because the source context needs attention.</p>}
    </details>
  </section>;
}
