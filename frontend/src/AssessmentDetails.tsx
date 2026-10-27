import type { Candidate } from './api';
import type { ReviewSection } from './reviewReadiness';
import { assessmentLabels } from './assessmentReadiness';

const duplicateLabels = {duplicate: 'Likely duplicate', distinct: 'Separate requirement', conflict: 'Conflicting requirement', uncertain: 'Needs comparison'};
const sections: Record<string, string> = {instruction: 'Review instruction', classification: 'Review classification',
  conditions: 'Review conditions', verification: 'Review verification', evidence: 'Review source', advanced: 'Resolve questions'};
const checkLabels: Record<string, string> = {
  source_accuracy: 'Matches the source', applicability: 'When the rule applies', exceptions: 'Exceptions',
  classification: 'Rule classification', verification: 'How the rule is verified',
};
const resultLabels: Record<string, string> = {supported: 'No issue found', correction: 'Needs correction', uncertain: 'Needs review'};
export default function AssessmentDetails({candidate, dirty, goTo, onOpenRelated}: {
  candidate: Candidate; dirty: boolean; goTo: (section: ReviewSection) => void; onOpenRelated?: (id: string) => void;
}) {
  const assessment = candidate.assessment;
  if (!assessment) return null;
  const stale = dirty || candidate.assessment_stale;
  return <section className={`assessment-detail ${stale ? 'stale' : assessment.outcome}`} aria-label="Rule assessment">
    <h3>{stale ? 'Check this rule again' : assessmentLabels[assessment.outcome]}</h3>
    {stale ? <p>This rule or a similar rule has changed. Save your edits and check it again to update the recommendation.</p> : <>
      {assessment.outcome === 'ready' ? <p>No outstanding issues were found in the checks performed. Review the source and approve when ready.</p>
        : <><strong>What needs attention</strong><ul>{assessment.issues.map((issue, i) => <li key={i}>
          <p>{issue.action.replaceAll('Jev', 'The automated check')}</p><div className="action-row"><button className="text-button" onClick={() => goTo(issue.section)}>{sections[issue.section]} →</button>
            {onOpenRelated && (issue.related_rule_ids || []).map((id, index) => <button className="text-button" key={id} onClick={() => onOpenRelated(id)}>Open matching rule {index + 1} →</button>)}
          </div></li>)}</ul></>}
    </>}
    {!!assessment.duplicates?.length && <div className="assessment-duplicates"><strong>{stale ? 'Previous comparisons' : 'Similar rules'}</strong>
      <p>Compared {assessment.duplicates.length} of {assessment.duplicate_candidates} likely matches.</p>
      <ul>{assessment.duplicates.map(match => <li key={match.rule_id}><strong>{Math.min(match.confidence, match.probabilities[match.choice]) < assessment.threshold ? 'Needs comparison' : duplicateLabels[match.choice]}</strong> · {match.title}
        <span className="muted"> · PDF pages {match.source_pages.join(', ')}</span>
        {!stale && onOpenRelated && <button className="text-button" onClick={() => onOpenRelated(match.rule_id)}>Open compared rule →</button>}
      </li>)}</ul>
    </div>}
    <details><summary>{stale ? 'Previous check details' : 'What was checked'}</summary>
      <p>Checked {new Date(assessment.assessed_at).toLocaleString()}.</p>
      <p>Source: PDF pages {assessment.source_pages.join(', ') || 'unavailable'}. Checks cover source text and likely matches with other rules. Images and less obvious duplicates may need your review.</p>
      {assessment.dimensions.length ? <table><thead><tr><th>Check</th><th>Result</th></tr></thead><tbody>{assessment.dimensions.map(d => <tr key={d.name}>
        <td>{checkLabels[d.name] || 'Additional check'}</td><td>{Math.min(d.confidence, d.probabilities[d.choice]) < assessment.threshold ? 'Needs review' : resultLabels[d.choice] || 'Needs review'}</td>
      </tr>)}</tbody></table> : <p>The source information needs attention before checks can be completed.</p>}
    </details>
  </section>;
}
