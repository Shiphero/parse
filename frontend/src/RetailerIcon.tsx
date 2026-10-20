import { useState } from 'react';

type RetailerIdentity = { name: string; icon_url?: string | null };
export default function RetailerIcon({ retailer, large = false }: { retailer: RetailerIdentity; large?: boolean }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const initials = retailer.name.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase();
  return <span className={`retailer-avatar${large ? ' retailer-avatar-large' : ''}`} aria-hidden="true">
    {retailer.icon_url && failedUrl !== retailer.icon_url
      ? <img src={retailer.icon_url} alt="" onError={() => setFailedUrl(retailer.icon_url || null)}/>
      : initials}
  </span>;
}
