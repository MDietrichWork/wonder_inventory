import type { Bootstrap } from "./types";

const API = "/api";

export async function getBootstrap(): Promise<Bootstrap> {
  const r = await fetch(`${API}/bootstrap`);
  if (!r.ok) throw new Error(`bootstrap failed: ${r.status}`);
  return r.json();
}

export async function apiPost(path: string, body?: any): Promise<any> {
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${path} failed: ${r.status}`);
  return r.json();
}

export async function getBreakdown(pk: number): Promise<any> {
  const r = await fetch(`${API}/exceptions/${pk}/breakdown`);
  return r.json();
}

export function jiraUrl(meta: Bootstrap["meta"], key: string): string | null {
  if (!meta.jiraBaseUrl || !key || key === "—") return null;
  return `${meta.jiraBaseUrl}/browse/${key}`;
}
