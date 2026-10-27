import type { Candidate, CheckDefinition, RuleSpec, RuleTypeDefinition } from './api';

export type ReviewSection = 'instruction' | 'classification' | 'conditions' | 'verification' | 'evidence' | 'reviewer' | 'advanced';
export type ReviewTask = { section: ReviewSection; label: string };

// Immediate form guidance. The API still validates the full contract and source on approval.
export function reviewTasks(spec: RuleSpec, candidate: Candidate, actor: string,
  types: RuleTypeDefinition[], checks: CheckDefinition[]): ReviewTask[] {
  const tasks: ReviewTask[] = [];
  const add = (section: ReviewSection, label: string) => tasks.push({section, label});
  if (!spec.title.trim()) add('instruction', 'Add a rule title');
  if (!spec.instruction.trim()) add('instruction', 'Add the instruction');
  if (!spec.purpose || spec.purpose === 'unclassified') add('classification', 'Choose guidance or shipment validation');
  if (!spec.operational_category || spec.operational_category === 'unclassified') add('classification', 'Choose an operational category');
  if (!spec.consumption_points?.length) add('classification', 'Choose where this rule is used');
  if (!spec.applicability_text.trim()) add('conditions', 'Describe when this rule applies');
  const type = types.find(t => t.id === spec.rule_type?.id);
  const instructionOnly = type && !type.check_ids.length && ['human', 'external_evidence'].includes(spec.verification) && !spec.assertion;
  if (spec.execution_mode !== 'reference_only' && spec.schema_version === '1.2' && spec.purpose === 'shipment_validation' && !spec.standard_check && !instructionOnly)
    add('verification', 'Choose a standard verification check');
  const check = checks.find(c => c.id === spec.standard_check?.check_id);
  if (check && spec.standard_check) {
    const parameters = spec.standard_check.parameters as Record<string, unknown>;
    const properties = check.parameters_schema.properties as Record<string, {type?:string; enum?:unknown[]; minimum?:number; maximum?:number; exclusiveMinimum?:number; minItems?:number}>;
    for (const field of (check.parameters_schema.required || []) as string[]) {
      const value = parameters[field];
      const property = properties[field];
      const invalid = value == null || value === '' ||
        (property.enum && !property.enum.includes(value)) ||
        (Array.isArray(value) && value.length < (property.minItems ?? 1)) ||
        (typeof value === 'number' && (!Number.isFinite(value) ||
          (property.minimum != null && value < property.minimum) ||
          (property.maximum != null && value > property.maximum) ||
          (property.exclusiveMinimum != null && value <= property.exclusiveMinimum) ||
          (property.type === 'integer' && !Number.isInteger(value))));
      if (invalid) add('verification', `Complete ${field.replaceAll('_', ' ')}`);
    }
  }
  if (!spec.evidence.length || spec.evidence.some(e => !e.quote.trim())) add('evidence', 'Add a source excerpt or image description');
  if (candidate.evidence_issues?.length && JSON.stringify(spec.evidence) === JSON.stringify(candidate.spec.evidence))
    add('evidence', 'Correct the source references');
  if (!actor.trim()) add('reviewer', 'Enter your reviewer name');
  return tasks;
}
