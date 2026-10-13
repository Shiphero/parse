import { useEffect, useState } from 'react';
import type { components } from './api.generated';
export type Library = components['schemas']['GuideLibrary'];
export type Guide = components['schemas']['GuideSummary'];
export type GuideDetail = components['schemas']['GuideDetail'];
export type PageDetail = components['schemas']['GuidePageDetail'];
export type UploadResult = components['schemas']['UploadResult'];

export async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...options, headers: { 'X-Requested-With': 'routing-guide-parser', ...options?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((d: { loc?: string[]; msg: string }) => `${d.loc?.at(-1) || 'Field'}: ${d.msg}`).join('. ')
      : 'We could not complete that request. Please try again.');
  }
  return response.json() as Promise<T>;
}

export function useRemote<T>(url: string, poll = 0, revision = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  useEffect(() => { setData(null); }, [url]);
  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    setError('');
    const load = async () => {
      if (pending) return;
      pending = true;
      try {
        const result = await request<T>(url, { signal: controller.signal });
        if (!controller.signal.aborted) { setData(result); setError(''); }
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to load this page.');
      } finally { pending = false; }
    };
    void load();
    const timer = poll ? window.setInterval(() => void load(), poll) : undefined;
    return () => { controller.abort(); if (timer) window.clearInterval(timer); };
  }, [url, poll, tick, revision]);
  return { data, error, reload: () => setTick(x => x + 1) };
}

export const statusNames: Record<Guide['status'], string> = {
  queued: 'Waiting to prepare', preparing: 'Preparing pages', ready: 'Pages ready',
  needs_attention: 'Needs attention', failed: 'Preparation failed',
};
export function formatDate(value: string | null, fallback = 'Not specified') {
  if (!value) return fallback;
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    .format(new Date(value.length === 10 ? `${value}T12:00:00` : value));
}
export function fileSize(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export type Workflow = components['schemas']['WorkflowView'];
export type Run = components['schemas']['RunView'];
export type Candidate = components['schemas']['Candidate'];
export type RuleSpec = components['schemas']['RuleSpec-Output'];
export type Release = components['schemas']['ReleaseView'];
export type Scenario = components['schemas']['ScenarioView'];
export type Evaluation = components['schemas']['EvaluationView'];
export type Connection = components['schemas']['ConnectionView'];
export type PublishAction = components['schemas']['PublishAction'];
export function jsonRequest<T>(url: string, body: unknown, method = 'POST') { return request<T>(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }

export type Comparison = components['schemas']['ComparisonView'];

export type CheckDefinition = components['schemas']['CheckDefinition'];
export type CheckStatus = components['schemas']['CheckStatus'];
