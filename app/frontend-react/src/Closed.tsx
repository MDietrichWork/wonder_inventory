import { useState, useMemo } from "react";
import type { Bootstrap, Exception } from "./types";
import { SEVRANK, labelFor } from "./lib";
import { sevPill, statusPill, Select } from "./Workbench";

// Columns tuned for reviewing closures (vs the open-triage Workbench): when + how it closed and how
// long it took, rather than age / recurrence.
const COLS: { key: string; label: string; cls?: string; num?: boolean }[] = [
  { key: "id", label: "Error ID", cls: "mono" },
  { key: "errorType", label: "Error Type" },
  { key: "severity", label: "Severity" },
  { key: "facility", label: "Facility", cls: "mono" },
  { key: "system", label: "System" },
  { key: "team", label: "Routed Team" },
  { key: "primaryOwner", label: "Primary Owner" },
  { key: "resolved", label: "Closed On", cls: "mono" },
  { key: "how", label: "How" },
  { key: "turnaround", label: "Turnaround (d)", cls: "num", num: true },
  { key: "jira", label: "JIRA Key", cls: "mono" },
  { key: "jiraStatus", label: "JIRA Status" },
];

const howOf = (e: Exception) => (e.autoClosed ? "Auto-closed" : "Manually resolved");

const uniq = (exc: Exception[], key: keyof Exception) =>
  Array.from(new Set(exc.map((e) => e[key]).filter(Boolean) as string[])).sort();

export function Closed({ data, onOpen }: { data: Bootstrap; onOpen: (e: Exception) => void }) {
  // Only closed / auto-closed tickets. (Open tickets live on the Workbench.)
  const exc = useMemo(() => data.exceptions.filter((e) => !e.isOpen), [data.exceptions]);
  const [f, setF] = useState({ q: "", facility: "", system: "", errortype: "", severity: "", team: "", how: "" });
  const [sortKey, setSortKey] = useState<string>("resolved");
  const [sortDir, setSortDir] = useState(-1);   // most-recently-closed first

  const set = (k: string, v: string) => setF((p) => ({ ...p, [k]: v }));
  const clearFilters = () => setF({ q: "", facility: "", system: "", errortype: "", severity: "", team: "", how: "" });

  const rows = useMemo(() => {
    const out = exc.filter((e) => {
      if (f.facility && e.facility !== f.facility) return false;
      if (f.system && e.system !== f.system) return false;
      if (f.errortype && e.errorType !== f.errortype) return false;
      if (f.severity && e.severity !== f.severity) return false;
      if (f.team && e.team !== f.team) return false;
      if (f.how && howOf(e) !== f.how) return false;
      if (f.q) {
        const hay = (e.id + " " + e.entityKey + " " + e.jira + " " + e.errorType + " " + labelFor(data.errorTypes, e.errorType) + " " + e.primaryOwner + " " + e.facility).toLowerCase();
        if (!hay.includes(f.q.toLowerCase())) return false;
      }
      return true;
    });
    out.sort((a, b) => {
      let va: any, vb: any;
      if (sortKey === "severity") { va = SEVRANK[a.severity]; vb = SEVRANK[b.severity]; }
      else if (sortKey === "how") { va = howOf(a); vb = howOf(b); }
      else { va = (a as any)[sortKey]; vb = (b as any)[sortKey]; }
      // null-safe: push nullish (e.g. no turnaround) to the end
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (va < vb) return -1 * sortDir;
      if (va > vb) return 1 * sortDir;
      return 0;
    });
    return out;
  }, [exc, f, sortKey, sortDir, data.errorTypes]);

  const sort = (k: string) => { if (sortKey === k) setSortDir((d) => -d); else { setSortKey(k); setSortDir(1); } };

  return (
    <section className="view active">
      <div className="page-head">
        <h1>Closed / Resolved</h1>
        <p>Tickets that have closed — auto-closed once the underlying data was fixed, or resolved manually. Review recent closures, filter by how they closed, and click any row for the full snapshot, resolution correction, and JIRA timeline.</p>
      </div>

      <div className="toolbar">
        <label className="flt">Search <input type="search" placeholder="Error ID, SKU, PO, JIRA…" value={f.q} onChange={(e) => set("q", e.target.value)} /></label>
        <span className="vline" />
        <label className="flt">Facility <Select v={f.facility} set={(v) => set("facility", v)} opts={uniq(exc, "facility")} all="All facilities" /></label>
        <label className="flt">System <Select v={f.system} set={(v) => set("system", v)} opts={uniq(exc, "system")} all="All systems" /></label>
        <label className="flt">Error type <Select v={f.errortype} set={(v) => set("errortype", v)} opts={uniq(exc, "errorType")} all="All error types" labelFn={(o) => labelFor(data.errorTypes, o)} /></label>
        <label className="flt">Severity <Select v={f.severity} set={(v) => set("severity", v)} opts={["Urgent", "High", "Medium", "Low"]} all="All severities" /></label>
        <label className="flt">Team <Select v={f.team} set={(v) => set("team", v)} opts={Object.keys(data.teams)} all="All teams" /></label>
        <label className="flt">How closed <Select v={f.how} set={(v) => set("how", v)} opts={["Auto-closed", "Manually resolved"]} all="Any" /></label>
        <span className="vline" />
        <button className="btn ghost sm" onClick={clearFilters}>Clear filters</button>
        <span className="spacer" />
        <span className="result-meta" dangerouslySetInnerHTML={{ __html: `Showing <b>${rows.length}</b> of <b>${exc.length}</b> closed` }} />
      </div>

      <div className="grid-wrap">
        <table className="grid">
          <thead><tr>
            {COLS.map((c) => (
              <th key={c.key} className={c.num ? "num" : ""} onClick={() => sort(c.key)}>
                {c.label}{sortKey === c.key && <span className="arr">{sortDir > 0 ? "▲" : "▼"}</span>}
              </th>
            ))}
          </tr></thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.pk} className="row" tabIndex={0} onClick={() => onOpen(e)}>
                {COLS.map((c) => {
                  if (c.key === "severity") return <td key="severity">{sevPill(e.severity)}</td>;
                  if (c.key === "jiraStatus") return <td key="jiraStatus">{statusPill(e.jiraStatus)}</td>;
                  if (c.key === "errorType") return <td key="errorType">{labelFor(data.errorTypes, e.errorType)}</td>;
                  if (c.key === "how") return (
                    <td key="how"><span className={"pill " + (e.autoClosed ? "rs-live" : "rs-catalog")}>{howOf(e)}</span></td>
                  );
                  if (c.key === "turnaround") return <td key="turnaround" className="num">{e.turnaround == null ? "—" : e.turnaround}</td>;
                  if (c.key === "resolved") return <td key="resolved" className="mono">{e.resolved || "—"}</td>;
                  return <td key={c.key} className={c.cls || ""}>{String((e as any)[c.key])}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <div className="empty">No closed tickets match the current filters.</div>}
      </div>
    </section>
  );
}
