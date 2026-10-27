import type { Candidate } from './api';

export type AssessmentFilter = 'all' | 'ready' | 'needs_correction' | 'needs_review' | 'stale' | 'unassessed';
export const assessmentLabels: Record<AssessmentFilter, string> = {
  all: 'All assessments', ready: 'Ready for approval', needs_correction: 'Needs correction',
  needs_review: 'Needs human review', stale: 'Reassessment needed', unassessed: 'Not assessed',
};
export function assessmentState(candidate: Candidate): Exclude<AssessmentFilter, 'all'> {
  if (!candidate.assessment) return 'unassessed';
  if (candidate.assessment_stale) return 'stale';
  return candidate.assessment.outcome;
}
