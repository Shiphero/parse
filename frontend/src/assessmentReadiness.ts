import type { Candidate } from './api';

export type AssessmentFilter = 'all' | 'ready' | 'needs_correction' | 'needs_review' | 'stale' | 'unassessed';
export const assessmentLabels: Record<AssessmentFilter, string> = {
  all: 'All results', ready: 'Ready for approval', needs_correction: 'Needs correction',
  needs_review: 'Needs attention', stale: 'Check again', unassessed: 'Not checked',
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

export function reviewFailure(job: Record<string, unknown> | null | undefined) {
  const reason = String(job?.reason || '');
  const saved = typeof job?.error === 'string' ? job.error.replaceAll('Continue checking', 'Resume review') : '';
  // Older jobs saved the provider rejection without a reason code.
  const incompatible = reason === 'provider_configuration' || saved.includes('rejected the extraction tool settings');
  const canContinue = !incompatible && !['configuration_required', 'version_changed', 'repeated_invalid_responses'].includes(reason);
  const message = incompatible
    ? 'Automatic review stopped because the selected model could not accept the request. This needs an application update; retrying the same run will not fix it. Your completed work is saved.'
    : reason === 'configuration_required' ? 'Open Connections and configure automated review, then start a new review.'
    : reason === 'repeated_invalid_responses' ? 'The AI service repeatedly returned unusable results. Finished work is saved. Contact your administrator before retrying.'
    : reason === 'version_changed' ? 'The review process has been updated. Use the main review button above to start again. Finished work is saved.'
    : saved || 'The review stopped before finishing. Choose Resume review to continue. Finished work is saved; contact your administrator if it stops again.';
  return {message, canContinue};
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
