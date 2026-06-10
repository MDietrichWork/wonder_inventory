import type { Exception } from "./types";

export function countBy<T>(rows: T[], key: ((r: T) => string) | keyof T): Record<string, number> {
  const m: Record<string, number> = {};
  rows.forEach((r) => {
    const k = typeof key === "function" ? (key as (r: T) => string)(r) : String(r[key as keyof T]);
    m[k] = (m[k] || 0) + 1;
  });
  return m;
}

// Inventory movement category for an exception (drives the "by movement type" breakout).
export function movementOf(e: Exception): string {
  const t = e.snapshot && e.snapshot.txn_type;
  if (e.errorType === "TRANSFER_WAREHOUSE_IMBALANCE") return "Transfer";
  if (e.errorType === "MISSING_LOT_EXPIRATION") return "Expiration";
  if (t === "PO_RECEIPT" || t === "ADD") return "PO Receipt";
  if (t === "CONSUME" || t === "PRODUCE_CONSUME") return "Production";
  if (t === "SHIP") return "Sales / Outbound";
  if (e.table === "po_table") return "PO Receipt";
  return "Adjustment";
}

export const statusClass = (s: string) => "st-" + s.replace(/[^A-Za-z]/g, "");

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
