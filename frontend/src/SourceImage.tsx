import { useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import type { RuleSpec } from './api';
type Reference = RuleSpec['evidence'][number];

export function SourceImage({guideId,evidence}: {guideId:string;evidence:Reference}) {
  const [size,setSize]=useState({width:1,height:1});
  const [failed,setFailed]=useState(false);
  const [x,y,w,h]=evidence.region||[0,0,1,1];
  if (![x,y,w,h].every(Number.isFinite)||x<0||y<0||w<=0||h<=0||x+w>1||y+h>1) return <p className="error">Adjust the image bounds to fit inside the page.</p>;
  return <figure className="source-illustration">
    {failed?<p className="error">Source image could not be loaded. Open the original PDF to inspect it.</p>:<div className="source-crop" style={{aspectRatio:`${size.width*w} / ${size.height*h}`}}>
      <img src={`/api/guides/${guideId}/pages/${evidence.page-1}/image`} alt={evidence.quote} onError={()=>setFailed(true)} onLoad={e=>setSize({width:e.currentTarget.naturalWidth,height:e.currentTarget.naturalHeight})} style={{width:`${100/w}%`,left:`${-x/w*100}%`,top:`${-y/h*100}%`}}/>
    </div>}
    <figcaption>{evidence.quote} · PDF page {evidence.page}</figcaption>
  </figure>;
}

export function RegionPicker({guideId,evidence,onChange}: {guideId:string;evidence:Reference;onChange:(region:number[]|null)=>void}) {
  const start=useRef<[number,number]|null>(null);
  const [draft,setDraft]=useState<number[]|null>(null);
  const point=(e:PointerEvent<HTMLDivElement>):[number,number]=>{const rect=e.currentTarget.getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(e.clientY-rect.top)/rect.height))];};
  const rectangle=(end:[number,number])=>{const from=start.current!;return [Math.min(from[0],end[0]),Math.min(from[1],end[1]),Math.abs(from[0]-end[0]),Math.abs(from[1]-end[1])];};
  const region=draft||evidence.region;
  return <div className="region-picker"><p className="muted">Drag over the diagram to choose the image shown with this rule, or enter its bounds below. Coordinates are percentages of the original page.</p>
    <div className="region-canvas" onPointerDown={e=>{if(e.button!==0)return;start.current=point(e);e.currentTarget.setPointerCapture(e.pointerId);setDraft(null);}} onPointerMove={e=>{if(start.current)setDraft(rectangle(point(e)));}} onPointerUp={e=>{if(!start.current)return;const next=rectangle(point(e));start.current=null;setDraft(null);if(next[2]>.005&&next[3]>.005)onChange(next);}} onPointerCancel={()=>{start.current=null;setDraft(null);}}>
      <img draggable={false} src={`/api/guides/${guideId}/pages/${evidence.page-1}/image`} alt={`Select a diagram on PDF page ${evidence.page}`}/>
      {region&&<span className="evidence-region" style={{left:`${region[0]*100}%`,top:`${region[1]*100}%`,width:`${region[2]*100}%`,height:`${region[3]*100}%`}}/>}
    </div>
    <div className="region-coordinates">{['Left','Top','Width','Height'].map((label,i)=><label key={label}>{label} %<input type="number" min={0} max={100} step={0.1} value={Number(((evidence.region||[0,0,1,1])[i]*100).toFixed(2))} onChange={e=>{const next=[...(evidence.region||[0,0,1,1])];next[i]=Number(e.target.value)/100;onChange(next);}}/></label>)}</div>
    <button className="text-button" onClick={()=>onChange(null)}>Use whole page</button>
  </div>;
}
