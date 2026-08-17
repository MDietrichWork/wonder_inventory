import type { Bootstrap } from "./types";

const API = "/api";

export async function getBootstrap(): Promise<Bootstrap> {
  const r = await fetch(`${API}/bootstrap`);
  if (!r.ok) throw new Error(`bootstrap failed: ${r.status}`);
  return r.json();
}

export async function getRunInfo(): Promise<{ runDate: string }> {
  const r = await fetch(`${API}/runinfo`);
  if (!r.ok) throw new Error(`runinfo failed: ${r.status}`);
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

export async function apiPatch(path: string, body: any): Promise<any> {
  const r = await fetch(`${API}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${path} failed: ${r.status}`);
  return r.json();
}

export async function putThresholds(
  bands: { errorType: string; facilityType: string; high: number; urgent: number }[]
): Promise<{ updated: number }> {
  const r = await fetch(`${API}/thresholds`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bands }),
  });
  if (!r.ok) throw new Error(`thresholds update failed: ${r.status}`);
  return r.json();
}

export async function putWasteCombos(
  combos: { l1Action: string; l2Action: string; enabled: boolean }[]
): Promise<{ total: number; enabled: number; added: number; removed: number; updated: number }> {
  const r = await fetch(`${API}/waste-combos`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ combos }),
  });
  if (!r.ok) throw new Error(`waste combos update failed: ${r.status}`);
  return r.json();
}

export async function putRetention(days: number): Promise<{ days: number }> {
  const r = await fetch(`${API}/retention`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ days }),
  });
  if (!r.ok) throw new Error(`retention update failed: ${r.status}`);
  return r.json();
}

export async function purgeClosed(): Promise<{ purged: number; olderThanDays: number }> {
  const r = await fetch(`${API}/retention/purge`, { method: "POST" });
  if (!r.ok) throw new Error(`purge failed: ${r.status}`);
  return r.json();
}

export async function putXferAging(noPickDays: number, notReceivedDays: number): Promise<{ noPickDays: number; notReceivedDays: number }> {
  const r = await fetch(`${API}/xfer-aging`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ noPickDays, notReceivedDays }),
  });
  if (!r.ok) throw new Error(`xfer aging update failed: ${r.status}`);
  return r.json();
}

export async function getBreakdown(pk: number): Promise<any> {
  const r = await fetch(`${API}/exceptions/${pk}/breakdown`);
  return r.json();
}

export async function getTransferBreakdown(pk: number): Promise<any> {
  const r = await fetch(`${API}/exceptions/${pk}/transfer-breakdown`);
  return r.json();
}

export function jiraUrl(meta: Bootstrap["meta"], key: string): string | null {
  if (!meta.jiraBaseUrl || !key || key === "—") return null;
  return `${meta.jiraBaseUrl}/browse/${key}`;
}
