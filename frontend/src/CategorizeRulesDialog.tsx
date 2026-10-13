import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { jsonRequest } from './api';
import type { Candidate, RuleSpec, Run } from './api';
import { consumptionPointOptions, operationalCategoryLabels } from './ruleTaxonomy';
import { rulePurposeLabels } from './rulePurpose';

type Category = NonNullable<RuleSpec['operational_category']>;
type Consumer = NonNullable<RuleSpec['consumption_points']>[number];

export default function CategorizeRulesDialog({ runId, version, rules, actor, onActorChange, onSave, onClose }: {
  runId: string; version: number; rules: Candidate[]; actor: string;
  onActorChange: (value: string) => void; onSave: (changed: number) => void; onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const first = rules[0].spec;
  const [category, setCategory] = useState<Category>(rules.every(r => r.spec.operational_category === first.operational_category) ? first.operational_category || 'unclassified' : 'unclassified');
  const [purpose, setPurpose] = useState<RuleSpec['purpose']>(rules.every(r => r.spec.purpose === first.purpose) ? first.purpose || 'unclassified' : 'unclassified');
  const [consumers, setConsumers] = useState<Consumer[]>(rules.every(r => JSON.stringify([...(r.spec.consumption_points || [])].sort()) === JSON.stringify([...(first.consumption_points || [])].sort())) ? first.consumption_points || [] : []);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { ref.current?.showModal(); }, []);
  const complete = category !== 'unclassified' && purpose !== 'unclassified' && consumers.length > 0 && !!actor.trim();
  const save = async () => {
    if (!complete || busy) return;
    setBusy(true); setError('');
    try {
      const updated = await jsonRequest<Run>(`/api/analysis/${runId}/classify`, {
        version, actor, note, revisions: Object.fromEntries(rules.map(r => [r.id, r.revision])),
        purpose, operational_category: category, consumption_points: consumers,
      });
      onSave(rules.filter(r => updated.payload.rules.find(next => next.id === r.id)?.revision !== r.revision).length);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <dialog ref={ref} className="upload-dialog categorize-dialog" aria-labelledby="categorize-title" onCancel={event => { if (busy) event.preventDefault(); else onClose(); }}>
    <div className="dialog-heading"><div><h2 id="categorize-title">Categorize {rules.length === 1 ? 'rule' : `${rules.length} rules`}</h2></div><button className="icon-button" aria-label="Close categorization" disabled={busy} onClick={onClose}><X/></button></div>
    <p className="dialog-description">{rules.length === 1 ? rules[0].spec.title : 'These choices will replace the categorization of every selected rule. Categorize rules with different activities separately.'}</p>
    <p className="notice">Choose all three: the activity, where the rule is consumed, and how it is used. General guidance is a rule use, not an operational category.</p>
    <fieldset disabled={busy} className="categorize-fields">
      <label>Operational category<select value={category} onChange={e => setCategory(e.target.value as Category)}><option value="unclassified" disabled>Choose the activity</option>{Object.entries(operationalCategoryLabels).filter(([key]) => key !== 'unclassified').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <fieldset className="consumption-points"><legend>Consumed by · choose at least one</legend>{consumptionPointOptions.map(([key, label]) => <label className="checkbox-label" key={key}><input type="checkbox" checked={consumers.includes(key as Consumer)} onChange={e => setConsumers(previous => e.target.checked ? [...previous, key as Consumer] : previous.filter(value => value !== key))}/>{label}</label>)}</fieldset>
      <label>Rule use<select value={purpose} onChange={e => setPurpose(e.target.value as RuleSpec['purpose'])}><option value="unclassified" disabled>Choose how this rule is used</option>{Object.entries(rulePurposeLabels).filter(([key]) => key !== 'unclassified').map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <p className="muted">General guidance stays in user instructions and is excluded from shipment checks. Saving complete categorization removes the rule from “Needs categorization”; it remains awaiting approval.</p>
      <label>Reviewer name<input value={actor} onChange={e => onActorChange(e.target.value)} autoComplete="name" placeholder="Your name"/></label>
      <label>Categorization note (optional)<input value={note} onChange={e => setNote(e.target.value)} placeholder="Why these choices apply"/></label>
    </fieldset>
    {error && <div className="error" role="alert">{error}</div>}
    <div className="dialog-footer"><button className="secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="primary" disabled={busy || !complete} onClick={save}>{busy ? 'Saving…' : 'Save categorization'}</button></div>
  </dialog>;
}
