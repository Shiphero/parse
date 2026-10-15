import { BookOpen, CircleHelp, Hand, Link2, Zap } from 'lucide-react';
import type { CheckStatus, RuleSpec, RuleTypeDefinition } from './api';
import { verificationSummary } from './rulePurpose';
import { activeWorkflows, consumptionPointLabels } from './ruleTaxonomy';

export function VerificationBadge({spec,status,compact=false}:{spec:RuleSpec;status?:CheckStatus;compact?:boolean}) {
  const verification=verificationSummary(spec,status);
  const Icon={automatic:Zap,manual:Hand,external:Link2,unresolved:CircleHelp,guidance:BookOpen}[verification.kind];
  const label=!compact&&['automatic','manual'].includes(verification.kind)?`${verification.label} verification`:verification.label;
  return <div className="verification-method">
    <span className={`verification-badge ${verification.kind} ${verification.unavailable?'unavailable':''}`} title={verification.detail}><Icon size={13} aria-hidden="true"/>{label}</span>
    {(!compact||verification.unavailable)&&<small className={verification.unavailable?'verification-unavailable':''}>{verification.detail}</small>}
  </div>;
}

export function WorkflowUsage({spec}:{spec:RuleSpec}) {
  const workflows=activeWorkflows(spec);
  return <div className="workflow-usage">{workflows.length?workflows.map(id=><span className="workflow-use" key={id}>{consumptionPointLabels[id]}</span>):<span className="usage-unassigned">{spec.rule_type&&spec.placements?.length?'All workflow placements off':'No workflow assigned'}</span>}</div>;
}

const behaviors={display:'Show instructions',confirm:'Ask for confirmation',warn:'Warn if check fails',block:'Block if check fails'};

export default function RuleUsage({spec,status,ruleType,onEditVerification,onEditWorkflows}:{spec:RuleSpec;status?:CheckStatus;ruleType?:RuleTypeDefinition;onEditVerification?:()=>void;onEditWorkflows?:()=>void}) {
  const placements=spec.rule_type?(spec.placements||[]).filter(p=>p.enabled!==false):[];
  const disabled=spec.rule_type?(spec.placements||[]).filter(p=>p.enabled===false).length:0;
  return <div className="rule-usage-summary">
    <div><div className="usage-heading"><strong>Verification</strong>{onEditVerification&&<button type="button" className="text-button" onClick={onEditVerification}>Edit verification</button>}</div><VerificationBadge spec={spec} status={status}/></div>
    <div><div className="usage-heading"><strong>Where it’s used</strong>{onEditWorkflows&&<button type="button" className="text-button" onClick={onEditWorkflows}>Edit workflows</button>}</div>
      {placements.length?<ul className="usage-placements">{placements.map(p=><li key={`${p.workflow}:${p.area}`}><strong>{consumptionPointLabels[p.workflow]}</strong><span>{ruleType?.allowed_placements.find(a=>a.workflow===p.workflow&&a.area===p.area)?.label||p.area.replaceAll('_',' ')} · {behaviors[p.behavior||'display']}</span></li>)}</ul>:<WorkflowUsage spec={spec}/>}
      {disabled>0&&<small className="usage-disabled">{disabled} workflow {disabled===1?'placement':'placements'} turned off</small>}
    </div>
  </div>;
}
