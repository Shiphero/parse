import { useEffect, useRef, useState } from 'react';
import { X, KeyRound } from 'lucide-react';
import { jsonRequest, request, useRemote } from './api';
import type { Connection } from './api';

export default function ConnectionsDialog({onClose}: {onClose: () => void}) {
  const ref = useRef<HTMLDialogElement>(null);
  const remote = useRemote<Connection[]>('/api/connections');
  const settings = useRemote<{max_upload_mb:number}>('/api/settings');
  const [uploadLimit, setUploadLimit] = useState(256);
  const [provider, setProvider] = useState('anthropic');
  const [key, setKey] = useState('');
  const [model, setModel] = useState('');
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { ref.current?.showModal(); }, []);
  useEffect(() => { if(settings.data)setUploadLimit(settings.data.max_upload_mb); }, [settings.data]);
  useEffect(() => { setModel(remote.data?.find(c=>c.id===provider)?.model || ''); }, [provider, remote.data]);
  useEffect(() => { setKey(''); setMessage(''); setAvailableModels([]); }, [provider]);
  const loadModels = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      const models = await request<string[]>('/api/connections/litellm/models');
      setAvailableModels(models);
      setMessage(models.length ? `${models.length} models available. Choose the exact alias for Gemini Argon or another model.` : 'This key has no available models. Ask the gateway administrator to grant access.');
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  };
  const save = async (clear = false) => {
    setBusy(true); setError(''); setMessage('');
    try {
      await jsonRequest('/api/connections/'+provider, {key: clear ? '' : key || null, model}, 'PUT');
      setKey(''); remote.reload(); setMessage(clear ? 'Credential removed from this connection.' : 'Settings saved. Access is checked when you run analysis, classification or import.');
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  };
  const configured = remote.data?.find(c=>c.id===provider)?.credential_configured;
  const managed = remote.data?.find(c=>c.id===provider)?.credential_managed;
  return <dialog ref={ref} className="upload-dialog" onCancel={onClose}><div className="dialog-heading"><div><span className="eyebrow">CONNECTIONS & SETTINGS</span><h2>Connect your tools</h2></div><button className="icon-button" onClick={onClose} aria-label="Close connections"><X/></button></div>
    <p className="dialog-description">Credentials stay on the server. Model preferences are saved in the database. Analysis sends guide text and images to the provider you select; classification sends rule text and source excerpts. Order data isn’t sent to AI.</p>
    <div className="form-field"><label htmlFor="provider">Connection</label><select id="provider" value={provider} disabled={busy} onChange={e=>{setProvider(e.target.value);setError('');}}><option value="anthropic">Claude / Anthropic</option><option value="openai">OpenAI</option><option value="litellm">LiteLLM</option><option value="jev">Jev / TypeSafe</option><option value="shiphero">ShipHero</option></select></div>
    {provider==='litellm' && <p className="muted">Gateway: {remote.data?.find(c=>c.id==='litellm')?.base_url || 'Not configured'}</p>}
    <p className="connection-status"><KeyRound size={15}/>{configured ? 'Credential saved · access not yet verified' : 'No credential configured'}</p>
    {managed?<p className="notice">Credentials are managed by the deployment through Secrets Manager. You can update the default model here.</p>:<div className="form-field"><label htmlFor="credential">{provider==='shiphero' ? 'Access token' : 'API key'}</label><input id="credential" type="password" autoComplete="new-password" value={key} disabled={busy||!remote.data} onChange={e=>setKey(e.target.value)} placeholder={configured ? 'Leave blank to keep the saved credential' : 'Paste your credential'}/></div>}
    {provider!=='shiphero' && <div className="form-field"><label htmlFor="model">Default model ID</label><input id="model" value={model} list={provider==='litellm'?'gateway-models':undefined} onChange={e=>setModel(e.target.value)} placeholder={provider==='jev'?'jev-1.14.0':provider==='litellm'?'Exact model alias from your gateway':'Exact vision-capable model ID from your provider'}/>{provider==='litellm' && <><datalist id="gateway-models">{availableModels.map(id=><option key={id} value={id}/>)}</datalist><button className="secondary" disabled={busy||!configured||!!key} onClick={loadModels}>Load available models</button><p className="form-hint">Save the key before loading models. Model access does not confirm image or structured-output compatibility.</p></>}<p className="form-hint spaced">{provider==='jev'?'Used for automatic readiness and duplicate checks on new analyses, and for rule classification. Rule text and source excerpts are sent to TypeSafe.':'Choose a model that supports images and structured output. You can change it for each analysis; incompatible selections return an error without falling back.'}</p></div>}
    {provider==='shiphero' && <p className="dialog-description">Read-only wholesale order import using the token’s account permissions. No ShipHero mutations are available.</p>}
    {(error || remote.error) && <div className="error" role="alert">{error || remote.error}</div>}{message && <p className="notice" role="status">{message}</p>}
    <div className="dialog-footer">{!managed&&<button className="secondary" disabled={busy || !configured} onClick={()=>save(true)}>Remove credential</button>}<button className="primary" disabled={busy||!remote.data} onClick={()=>save()}>{busy?'Saving…':managed?'Save model':'Save connection'}</button></div>
    <hr/>
    <div className="form-field"><label htmlFor="upload-limit">Maximum PDF upload size (MB)</label><input id="upload-limit" type="number" min={1} max={1024} value={uploadLimit} disabled={busy||!settings.data} onChange={e=>setUploadLimit(Number(e.target.value))}/></div>
    <button className="secondary" disabled={busy||!settings.data||!Number.isInteger(uploadLimit)||uploadLimit<1||uploadLimit>1024} onClick={async()=>{setBusy(true);setError('');setMessage('');try{await jsonRequest('/api/settings',{max_upload_mb:uploadLimit},'PUT');settings.reload();setMessage('Upload limit saved. Applies to new uploads.');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Save upload limit</button>
    {settings.error&&<p className="error">{settings.error}</p>}
  </dialog>;
}
