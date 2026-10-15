import { useEffect, useRef, useState } from 'react';
import { X, KeyRound } from 'lucide-react';
import { jsonRequest, useRemote } from './api';
import type { Connection } from './api';

export default function ConnectionsDialog({onClose}: {onClose: () => void}) {
  const ref = useRef<HTMLDialogElement>(null);
  const remote = useRemote<Connection[]>('/api/connections');
  const [provider, setProvider] = useState('anthropic');
  const [key, setKey] = useState('');
  const [model, setModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { ref.current?.showModal(); }, []);
  useEffect(() => { setModel(remote.data?.find(c=>c.id===provider)?.model || ''); }, [provider, remote.data]);
  useEffect(() => { setKey(''); setMessage(''); }, [provider]);
  const save = async (clear = false) => {
    setBusy(true); setError(''); setMessage('');
    try {
      await jsonRequest('/api/connections/'+provider, {key: clear ? '' : key || null, model}, 'PUT');
      setKey(''); remote.reload(); setMessage(clear ? 'Credential removed from this connection.' : 'Saved locally. Access is checked when you run analysis, classification or import.');
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  };
  const configured = remote.data?.find(c=>c.id===provider)?.credential_configured;
  return <dialog ref={ref} className="upload-dialog" onCancel={onClose}><div className="dialog-heading"><div><span className="eyebrow">LOCAL CONNECTIONS</span><h2>Connect your tools</h2></div><button className="icon-button" onClick={onClose} aria-label="Close connections"><X/></button></div>
    <p className="dialog-description">Credentials stay on this computer’s server, outside Git. Analysis sends guide text and images to the provider you select; classification sends rule text and source excerpts. Scenario checks run locally; order data isn’t sent to AI.</p>
    <div className="form-field"><label htmlFor="provider">Connection</label><select id="provider" value={provider} disabled={busy} onChange={e=>{setProvider(e.target.value);setError('');}}><option value="anthropic">Claude / Anthropic</option><option value="openai">OpenAI</option><option value="jev">Jev / TypeSafe</option><option value="shiphero">ShipHero</option></select></div>
    <p className="connection-status"><KeyRound size={15}/>{configured ? 'Credential saved · access not yet verified' : 'No credential configured'}</p>
    <div className="form-field"><label htmlFor="credential">{provider==='shiphero' ? 'Access token' : 'API key'}</label><input id="credential" type="password" autoComplete="new-password" value={key} onChange={e=>setKey(e.target.value)} placeholder={configured ? 'Leave blank to keep the saved credential' : 'Paste your credential'}/></div>
    {provider!=='shiphero' && <div className="form-field"><label htmlFor="model">Default model ID</label><input id="model" value={model} onChange={e=>setModel(e.target.value)} placeholder={provider==='jev'?'jev-1.14.0':'Exact vision-capable model ID from your provider'}/><p className="form-hint spaced">{provider==='jev'?'Used for rule classification. Select Jev in Review rules after saving. Rule text and source excerpts are sent to TypeSafe; verification settings stay unchanged.':'Choose a model that supports images and structured output. You can change it for each analysis; incompatible selections return an error without falling back.'}</p></div>}
    {provider==='shiphero' && <p className="dialog-description">Read-only wholesale order import using the token’s account permissions. Refresh expired access tokens here. No ShipHero mutations are available.</p>}
    {(error || remote.error) && <div className="error" role="alert">{error || remote.error}</div>}{message && <p className="notice" role="status">{message}</p>}
    <div className="dialog-footer"><button className="secondary" disabled={busy || !configured} onClick={()=>save(true)}>Remove credential</button><button className="primary" disabled={busy} onClick={()=>save()}>{busy?'Saving…':'Save connection'}</button></div>
  </dialog>;
}
