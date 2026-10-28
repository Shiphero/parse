import type { Candidate } from './api';

export type AssessmentFilter = 'all' | 'ready' | 'needs_correction' | 'needs_review' | 'stale' | 'unassessed';
export const assessmentLabels: Record<AssessmentFilter, string> = {
  all: 'All results', ready: 'Ready for approval', needs_correction: 'Needs correction',
  needs_review: 'Needs review', stale: 'Check again', unassessed: 'Not checked',
};
export function assessmentState(candidate: Candidate): Exclude<AssessmentFilter, 'all'> {
  if (!candidate.assessment) return 'unassessed';
  if (candidate.assessment_stale) return 'stale';
  return candidate.assessment.outcome;
}

export function readyForApprovalSelection(candidate: Candidate): boolean {
  if (candidate.status !== 'pending' || candidate.evidence_issues?.length) return false;
  if (candidate.assessment) return !candidate.assessment_stale && !candidate.assessment.check_failed && candidate.assessment.outcome === 'ready';
  return !candidate.individual_review_reasons.length;
}


export function reviewProgress(rules:Candidate[], job:Record<string,unknown>|null|undefined) {
  const pending=rules.filter(rule=>rule.status==='pending');
  const running=!!job&&['queued','running'].includes(String(job.status));
  const preparing=running&&job?.phase==='resolve';
  const visible=pending.filter(rule=>!running||(!preparing&&rule.assessment?.job_id===job?.id));
  const retry= pending.filter(rule=>!!rule.assessment?.check_failed ||
    (!!rule.resolution?.failed&&rule.resolution.revision===rule.revision));
  return {running,preparing,visible,retryCount:retry.length,
    checked:visible.filter(rule=>rule.assessment&&!rule.assessment_stale&&!rule.assessment.check_failed).length,
    currentFailures:running?Number(preparing?job?.resolution_failed:job?.failed)||0:retry.length};
}
