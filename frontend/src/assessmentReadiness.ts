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
