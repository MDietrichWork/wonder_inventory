import { useState, useMemo } from "react";
import type { Bootstrap, Drill, Exception } from "./types";
import { SEVRANK, statusClass } from "./lib";

const COLS: { key: keyof Exception | "currentHolder"; label: string; cls?: string; num?: boolean }[] = [
  { key: "id", label: "Error ID", cls: "mono" },
  { key: "runDate", label: "Run Date", cls: "mono" },
  { key: "errorType", label: "Error Type" },
  { key: "severity", label: "Severity" },
  { key: "facility", label: "Facility", cls: "mono" },
  { key: "system", label: "System" },
  { key: "entityKey", label: "Entity Key", cls: "mono" },
  { key: "team", label: "Routed Team" },
  { key: "primaryOwner", label: "Primary Owner" },
  { key: "currentHolder", label: "Assignee" },
  { key: "jira", label: "JIRA Key", cls: "mono" },
  { key: "jiraStatus", label: "JIRA Status" },
  { key: "age", label: "Age (d)", cls: "num", num: true },
  { key: "recurrence", label: "Recurrence", cls: "num", num: true },
];

export const sevPill = (s: string) => <span className={"pill sev sev-" + s}><span className={"sev-dot " + s} />{s}</span>;
export const statusPill = (s: string) => <span className={"status " + statusClass(s)}>{s}</span>;

const uniq = (exc: Exception[], key: keyof Exception) =>
  Array.from(new Set(exc.map((e) => e[key]).filter(Boolean) as string[])).sort();

export function Workbench({ data, drill, clearDrill, onOpen }: {
  data: Bootstrap; drill: Drill; clearDrill: () => void; onOpen: (e: Exception) => void;
}) {
  const exc = data.exceptions;
  const [f, setF] = useState({ q: "", facility: "", system: "", errortype: "", severity: "", status: "", team: "", owner: "" });
  const [sortKey, setSortKey] = useState<string>("severity");
  const [sortDir, setSortDir] = useState(1);

  const set = (k: string, v: string) => setF((p) => ({ ...p, [k]: v }));
  const clearFilters = () => { setF({ q: "", facility: "", system: "", errortype: "", severity: "", status: "", team: "", owner: "" }); clearDrill(); };

  const rows = useMemo(() => {
    const out = exc.filter((e) => {
      if (drill && !drill.test(e)) return false;
      if (f.facility && e.facility !== f.facility) return false;
      if (f.system && e.system !== f.system) return false;
      if (f.errortype && e.errorType !== f.errortype) return false;
      if (f.severity && e.severity !== f.severity) return false;
      if (f.status && e.jiraStatus !== f.status) return false;
      if (f.team && e.team !== f.team) return false;
      if (f.owner && e.primaryOwner !== f.owner) return false;
      if (f.q) {
        const hay = (e.id + " " + e.entityKey + " " + e.jira + " " + e.errorType + " " + e.primaryOwner + " " + e.currentHolder + " " + e.facility).toLowerCase();
        if (!hay.includes(f.q.toLowerCase())) return false;
      }
      return true;
    });
    out.sort((a, b) => {
      let va: any, vb: any;
      if (sortKey === "severity") { va = SEVRANK[a.severity]; vb = SEVRANK[b.severity]; }
      else { va = (a as any)[sortKey]; vb = (b as any)[sortKey]; }
      if (va < vb) return -1 * sortDir;
      if (va > vb) return 1 * sortDir;
      return b.age - a.age;
    });
    return out;
  }, [exc, drill, f, sortKey, sortDir]);

  const sort = (k: string) => { if (sortKey === k) setSortDir((d) => -d); else { setSortKey(k); setSortDir(1); } };

  return (
    <section className="view active">
      <div className="page-head">
        <h1>Exception Workbench</h1>
        <p>Triage flagged validation errors from the latest runs. Filter, sort, and click any row for the full snapshot, rule, ownership, and JIRA timeline.</p>
      </div>

      <div className="toolbar">
        <label className="flt">Search <input type="search" placeholder="Error ID, SKU, PO, JIRA…" value={f.q} onChange={(e) => set("q", e.target.value)} /></label>
        <span className="vline" />
        <label className="flt">Facility <Select v={f.facility} set={(v) => set("facility", v)} opts={uniq(exc, "facility")} all="All facilities" /></label>
        <label className="flt">System <Select v={f.system} set={(v) => set("system", v)} opts={uniq(exc, "system")} all="All systems" /></label>
        <label className="flt">Error type <Select v={f.errortype} set={(v) => set("errortype", v)} opts={data.errorTypes.map((t) => t.type)} all="All error types" /></label>
        <label className="flt">Severity <Select v={f.severity} set={(v) => set("severity", v)} opts={["Urgent", "High", "Medium", "Low"]} all="All severities" /></label>
        <label className="flt">Status <Select v={f.status} set={(v) => set("status", v)} opts={uniq(exc, "jiraStatus")} all="All statuses" /></label>
        <label className="flt">Team <Select v={f.team} set={(v) => set("team", v)} opts={Object.keys(data.teams)} all="All teams" /></label>
        <label className="flt" title="Everything this person is accountable for — handed-off tickets included.">Primary owner <Select v={f.owner} set={(v) => set("owner", v)} opts={uniq(exc, "primaryOwner")} all="All owners" /></label>
        <span className="vline" />
        <button className="btn ghost sm" onClick={clearFilters}>Clear filters</button>
        <span className="spacer" />
        <span className="result-meta" dangerouslySetInnerHTML={{ __html: `Showing <b>${rows.length}</b> of <b>${exc.length}</b> exceptions` }} />
      </div>

      {drill && (
        <div className="drillbar show">
          <span className="drill-from">Drilled from dashboard:</span>
          <span className="fchip">{drill.label}<button className="fchip-x" title="Clear" onClick={clearDrill}>✕</button></span>
        </div>
      )}

      <div className="grid-wrap">
        <table className="grid">
          <thead><tr>
            {COLS.map((c) => (
              <th key={c.key as string} className={c.num ? "num" : ""} onClick={() => sort(c.key as string)}>
                {c.label}{sortKey === c.key && <span className="arr">{sortDir > 0 ? "▲" : "▼"}</span>}
              </th>
            ))}
          </tr></thead>
          <tbody>
            {rows.map((e) => {
              const handed = e.currentHolder && e.currentHolder !== e.primaryOwner;
              return (
                <tr key={e.pk} className="row" tabIndex={0} onClick={() => onOpen(e)}>
                  {COLS.map((c) => {
                    if (c.key === "severity") return <td key="severity">{sevPill(e.severity)}</td>;
                    if (c.key === "jiraStatus") return <td key="jiraStatus">{statusPill(e.jiraStatus)}</td>;
                    if (c.key === "currentHolder") return (
                      <td key="currentHolder">{handed ? <>{e.currentHolder}<span className="subtag" title={"Held " + e.heldDays + "d"}>↳ held {e.heldDays}d</span></> : ""}</td>
                    );
                    return <td key={c.key as string} className={c.cls || ""}>{String((e as any)[c.key])}</td>;
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && <div className="empty">No exceptions match the current filters.</div>}
      </div>
    </section>
  );
}

function Select({ v, set, opts, all }: { v: string; set: (v: string) => void; opts: string[]; all: string }) {
  return (
    <select value={v} onChange={(e) => set(e.target.value)}>
      <option value="">{all}</option>
      {opts.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}
