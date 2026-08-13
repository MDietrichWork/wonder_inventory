import type { Exception } from "./types";

export function countBy<T>(rows: T[], key: ((r: T) => string) | keyof T): Record<string, number> {
  const m: Record<string, number> = {};
  rows.forEach((r) => {
    const k = typeof key === "function" ? (key as (r: T) => string)(r) : String(r[key as keyof T]);
    m[k] = (m[k] || 0) + 1;
  });
  return m;
}

// Inventory movement category for an exception — the ledger l1/l2 action captured at validation
// time. PO-table-only errors (e.g. missing price) have no ledger movement → "Non-Movement Errors".
export function movementOf(e: Exception): string {
  return (e.snapshot && e.snapshot.movement) || "Non-Movement Errors";
}

export const statusClass = (s: string) => "st-" + s.replace(/[^A-Za-z]/g, "");

// Human-readable name for an error_type code, from the bootstrap errorTypes (falls back to the code).
export function labelFor(errorTypes: { type: string; label?: string }[], type: string): string {
  const m = errorTypes.find((t) => t.type === type);
  return (m && m.label) || type;
}

// Turn a raw snake_case snapshot/field key into a friendly display label
// ("order_type" → "Order Type"). Domain acronyms are cased explicitly; every
// other word is Title Cased.
const KEY_ACRONYMS: Record<string, string> = {
  po: "PO", sku: "SKU", uom: "UoM", ims: "IMS", id: "ID", utc: "UTC", pct: "%",
};
export function humanizeKey(k: string): string {
  return k
    .split("_")
    .map((w) => KEY_ACRONYMS[w] ?? w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function fmtNum(v: any): string {
  if (v == null) return "—";
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function metrics(exc: Exception[], runDate: string) {
  const open = exc.filter((e) => e.isOpen);
  const newToday = exc.filter((e) => (e.detectedOn || e.created) === runDate);
  const autoClosedToday = exc.filter((e) => e.autoClosed && e.resolved === runDate);
  const resolvedAll = exc.filter((e) => e.turnaround != null);
  const avgTat = resolvedAll.length ? resolvedAll.reduce((s, e) => s + (e.turnaround || 0), 0) / resolvedAll.length : 0;
  const withinAll = exc.filter((e) => (!e.isOpen ? e.withinSla : e.age <= e.slaTarget));
  const pctSla = exc.length ? Math.round((100 * withinAll.length) / exc.length) : 0;
  const breaching = open.filter((e) => !e.withinSla).length;
  return { open: open.length, newToday: newToday.length, autoClosedToday: autoClosedToday.length, avgTat, pctSla, withinCount: withinAll.length, total: exc.length, breaching };
}

export const SEVRANK: Record<string, number> = { Urgent: 0, High: 1, Medium: 2, Low: 3 };
export const SYS_PAL = ["var(--accent)", "var(--brand-2)", "var(--teal)", "var(--ok)", "var(--high)", "var(--med)"];
