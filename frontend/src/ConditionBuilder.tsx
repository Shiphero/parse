import { useState } from 'react';
import type { RuleSpec } from './api';
import { conditionFields } from './conditionFields';

export type Condition = NonNullable<RuleSpec['applicability']>;
const operators = {eq:'equals', ne:'does not equal', lt:'less than', lte:'at most', gt:'more than', gte:'at least', exists:'is present'};
export const newCondition = (): Condition => ({op:'eq',path:'',value:null,unit:null,children:[]});

export function describeCondition(value: Condition | null | undefined): string {
  if (!value) return 'All subjects (no condition)';
  if (value.op === 'all' || value.op === 'any') return (value.children || []).map(child => `(${describeCondition(child)})`).join(value.op === 'all' ? ' AND ' : ' OR ');
  if (value.op === 'not') return `NOT (${describeCondition(value.children?.[0])})`;
  return `${value.path || 'Choose a field'} ${operators[value.op as keyof typeof operators] || value.op} ${value.op === 'exists' ? '' : `${value.value===null || value.value===undefined ? '…' : JSON.stringify(value.value)} ${value.unit || ''}`}`.trim();
}

export default function ConditionBuilder({value,onChange,subject,label='Apply this rule when'}: {value:Condition|null|undefined;onChange:(value:Condition|null)=>void;subject:RuleSpec['subject'];label?:string}) {
  const fields = conditionFields(subject);
  const knownField = fields.find(field=>field.path===value?.path);
  const [custom,setCustom] = useState(false);
  const customField = custom || (!!value?.path && !knownField);
  const simple = value && Object.prototype.hasOwnProperty.call(operators, value.op) && !Array.isArray(value.value) && !value.comparator;
  return <fieldset className="condition-builder"><legend>{label}</legend>
    {!value ? <><p className="muted">No expression configured. Choose a field and comparison to build this condition.</p><button className="secondary" onClick={()=>onChange(newCondition())}>Add condition</button></> : <>
      {(value.op === 'all' || value.op === 'any') ? <>
        <label>Match<select value={value.op} onChange={e=>onChange({...value,op:e.target.value as Condition['op']})}><option value="all">All conditions (AND)</option><option value="any">Any condition (OR)</option></select></label>
        {(value.children||[]).map((child,i)=><ConditionBuilder key={i} subject={subject} value={child} label={`Condition ${i+1}`} onChange={next=>{const children=(value.children||[]).flatMap((old,j)=>j===i?(next?[next]:[]):[old]);onChange(children.length?{...value,children}:null);}}/>)}
        <button className="text-button" onClick={()=>onChange({...value,children:[...(value.children||[]),newCondition()]})}>Add condition</button>
      </> : simple ? <>
        <div className="condition-fields"><label>Field<select aria-label={`${label}: field`} value={customField?'__custom':value.path||''} onChange={e=>{
            if(e.target.value==='__custom') {setCustom(true);onChange({...value,path:''});return;}
            const field=fields.find(item=>item.path===e.target.value);
            if(!field)return;
            setCustom(false);
            onChange({...value,path:field.path,op:value.op==='exists'?'exists':field.type==='text'&&value.op!=='ne'?'eq':value.op,value:value.op==='exists'?null:field.type==='text'?'':null,unit:value.op==='exists'?null:field.unit||null});
          }}><option value="" disabled>Choose a field…</option>{fields.map(field=><option key={field.path} value={field.path}>{field.label}</option>)}<option value="__custom">Custom field path…</option></select></label>
          <label>Comparison<select value={value.op} onChange={e=>onChange({...value,op:e.target.value as Condition['op'],value:e.target.value==='exists'?null:value.value??(knownField?.type==='text'?'':null),unit:e.target.value==='exists'?null:value.unit??knownField?.unit??null})}>{Object.entries(operators).map(([op,text])=><option key={op} value={op}>{text}</option>)}</select></label></div>
        {customField&&<label>Custom field path<input value={value.path||''} placeholder="e.g. evidence.label_position_verified" onChange={e=>onChange({...value,path:e.target.value})}/></label>}
        <p className="muted">{customField?'Use a dot-separated path from your scenario JSON. Custom fields must be supplied explicitly.':knownField?.help||'Fields must be present in the scenario. Missing values remain Cannot determine.'}</p>
        {value.op!=='exists'&&<div className="condition-fields"><label>Value type<select value={typeof value.value==='boolean'?'boolean':typeof value.value==='string'?'text':'number'} onChange={e=>onChange({...value,value:e.target.value==='boolean'?true:e.target.value==='text'?'':0,unit:e.target.value==='number'?value.unit:null})}><option value="number">Number</option><option value="text">Text</option><option value="boolean">Yes / no</option></select></label>
          <label>Value{typeof value.value==='boolean'?<select value={String(value.value)} onChange={e=>onChange({...value,value:e.target.value==='true'})}><option value="true">Yes</option><option value="false">No</option></select>:<input type={typeof value.value==='string'?'text':'number'} step="any" value={typeof value.value==='string'||typeof value.value==='number'?value.value:''} onChange={e=>onChange({...value,value:typeof value.value==='string'?e.target.value:e.target.value===''?null:Number(e.target.value)})}/>}</label>
          {typeof value.value!=='string'&&typeof value.value!=='boolean'&&<label>Unit<select value={value.unit||''} onChange={e=>onChange({...value,unit:(e.target.value||null) as Condition['unit']})}><option value="">No unit</option>{['in','cm','mm','oz','lb','g','kg'].map(unit=><option key={unit}>{unit}</option>)}</select></label>}</div>}
      </> : <p className="notice">This expression uses advanced logic. It is preserved; edit it in Advanced JSON below.</p>}
      <div className="action-row"><button className="text-button" onClick={()=>onChange({op:'all',children:[value,newCondition()]})}>Combine with another condition</button><button className="text-button" onClick={()=>onChange(null)}>Remove condition</button></div>
      <p className="condition-summary">{describeCondition(value)}</p>
    </>}
  </fieldset>;
}
