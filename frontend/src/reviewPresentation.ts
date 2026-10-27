import type { Candidate } from './api';
import type { ReviewTask } from './reviewReadiness';

export type ReviewJob = {status?:unknown; phase?:unknown; id?:unknown};
export function reviewPresentation(candidate:Candidate, tasks:ReviewTask[], editable:boolean, job?:ReviewJob|null) {
  const fields = tasks.filter(task=>task.section!=='reviewer');
  const running = !!job && ['queued','running'].includes(String(job.status));
  const currentResult = candidate.assessment && !candidate.assessment_stale && candidate.assessment.job_id===job?.id;
  if (candidate.status==='ignored') return candidate.review?.mode==='automatic_duplicate'
    ? {kind:'ignored',label:'Duplicate set aside',title:'Duplicate handled automatically',detail:'An identical requirement is already retained. The original text and evidence are saved here, and you can restore this rule.'}
    : {kind:'ignored',label:'Ignored',title:'Excluded from this draft',detail:'Restore this rule if you want to include it again.'};
  if (candidate.status==='rejected') return {kind:'rejected',label:'Rejected',title:'Rejected',detail:'This decision is saved in the rule history.'};
  if (candidate.status==='approved') return candidate.review?.mode==='automatic'
    ? {kind:'approved',label:'Auto-approved',title:'Approved automatically',detail:'The source and duplicate checks passed. No action is needed. You can return this rule to review if something looks wrong.'}
    : {kind:'approved',label:'Approved',title:'Approved',detail:'This decision is saved. No further action is needed.'};
  if (running && !currentResult) {
    const prepared = candidate.resolution?.revision===candidate.revision && !candidate.resolution.failed;
    return {kind:'working',label:job.phase==='resolve'?'Preparing':'Checking',title:prepared?'Rule details prepared — checks are still running':'Automatic review in progress',
      detail:prepared?'No action needed now. Accuracy and duplicate checks will follow. You can leave this rule pending.':'No action needed now. The app is checking the source and resolving what it can. You can browse or come back later.'};
  }
  if (!editable) return {kind:'readonly',label:'Read only',title:'Viewing a saved rule',detail:'This version cannot be edited here. Open a draft to make changes.'};
  if (fields.length) return {kind:'fields',label:'Missing information',title:`${fields.length} ${fields.length===1?'field needs':'fields need'} information`,detail:'The missing fields are listed below and marked in the editor. Leave this rule pending if the source does not answer them.'};
  if (!candidate.assessment) return {kind:'unchecked',label:'Not checked',title:'No missing fields identified',detail:'Automatic review has not finished for this rule. Run the checks before deciding; you can leave it pending.'};
  if (candidate.assessment_stale) return {kind:'stale',label:'Check again',title:'This rule needs a fresh check',detail:'The rule or its checks have changed. Run the checks again; the previous result is not a current decision.'};
  if (candidate.assessment.check_failed) return {kind:'attention',label:'Check incomplete',title:'Checks could not finish',detail:'Retry the failed checks. You do not need to make a decision now.'};
  if (candidate.assessment.outcome==='ready') return {kind:'ready',label:'Ready for approval',title:'Ready for approval',detail:'No outstanding issues were found in the completed checks. You can approve this rule with the other ready rules.'};
  const issues = candidate.assessment.issues || [];
  const label = issues.some(issue=>issue.code==='duplicate_conflict')?'Conflicting requirements'
    : issues.some(issue=>issue.code==='duplicate_duplicate')?'Possible duplicate'
    : issues.some(issue=>issue.code.startsWith('duplicate'))?'Compare these rules'
    : issues.some(issue=>issue.code==='visual_evidence')?'Check source image'
    : candidate.assessment.outcome==='needs_correction'?'Correction proposed':'Question remains';
  return {kind:'attention',label,title:label,detail:'Only the findings below need attention. Leave the rule pending when the source does not establish an answer.'};
}
