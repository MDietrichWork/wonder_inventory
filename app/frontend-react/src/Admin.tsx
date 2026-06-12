import { useState } from "react";
import type { Bootstrap } from "./types";
import { sevPill } from "./Workbench";
import { labelFor } from "./lib";

export function Admin({ data }: { data: Bootstrap }) {
  const [enabled, setEnabled] = useState<Record<string, boolean>>(Object.fromEntries(data.rules.map((r) => [r.id, r.enabled])));
  const [selId, setSelId] = useState(data.rules[0]?.id);
  const rule = data.rules.find((r) => r.id === selId) || data.rules[0];

  return (
    <section className="view active">
      <div className="page-head">
        <h1>Rule &amp; Routing Admin</h1>
        <p>The configurable layer: validation rules, the error-type → team → assignee → JIRA routing map, and SLA targets per severity. Editing is mocked in this prototype.</p>
      </div>
      <div className="scroll-pad">
        <div className="admin-grid">
          <div className="card">
            <h2>Validation rules</h2>
            <table className="mini">
              <thead><tr><th>Rule</th><th>Type</th><th>Target table</th><th>Severity</th><th className="num">Enabled</th></tr></thead>
              <tbody>
                {data.rules.map((r) => (
                  <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => setSelId(r.id)} className={selId === r.id ? "selected" : ""}>
                    <td><b>{r.name}</b><div className="tip mono">{r.id} → {r.errorType}</div></td>
                    <td><span className="tag">{r.type}</span></td>
                    <td className="mono">{r.target}</td>
                    <td>{sevPill(r.severity)}</td>
                    <td className="num">
                      <span className={"toggle" + (enabled[r.id] ? " on" : "")} role="switch" aria-checked={enabled[r.id]} tabIndex={0}
                        onClick={(ev) => { ev.stopPropagation(); setEnabled((p) => ({ ...p, [r.id]: !p[r.id] })); }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="muted-note">Click a rule to load it into the editor (read-only mock).</div>
          </div>

          <div className="card" id="rule-editor">
            <h2>Rule editor</h2>
            {rule && (
              <div id="rule-form">
                <FormRow label="Rule name"><input type="text" defaultValue={rule.name} /></FormRow>
                <FormRow label="Rule ID"><input type="text" value={rule.id} readOnly /></FormRow>
                <FormRow label="Rule type">
                  <select defaultValue={rule.type}>{["NOT_NULL", "REFERENTIAL", "RECONCILIATION", "RANGE"].map((t) => <option key={t}>{t}</option>)}</select>
                </FormRow>
                <FormRow label="Target table">
                  <select defaultValue={rule.target}>{data.sourceTables.map((t) => <option key={t}>{t}</option>)}</select>
                </FormRow>
                <FormRow label="Maps to error"><input type="text" value={labelFor(data.errorTypes, rule.errorType)} readOnly /></FormRow>
                <FormRow label="Severity">
                  <select defaultValue={rule.severity}>{["Urgent", "High", "Medium", "Low"].map((s) => <option key={s}>{s}</option>)}</select>
                </FormRow>
                <FormRow label="Expression / SQL">
                  <textarea rows={18} defaultValue={rule.expression}
                    style={{ width: "100%", background: "var(--surface-3)", border: "1px solid var(--line)", color: "#c8d3ec", borderRadius: 6, padding: 8, fontFamily: "var(--mono)", fontSize: 11, whiteSpace: "pre" }} />
                </FormRow>
                <FormRow label="Enabled"><span className={"toggle" + (enabled[rule.id] ? " on" : "")} /></FormRow>
                <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                  <button className="btn primary sm" onClick={() => alert("Mock: saved rule " + rule.id + ".")}>Save (mock)</button>
                  <button className="btn sm" onClick={() => alert("Mock: dry-validation for " + rule.id + ".")}>Run dry-validation (mock)</button>
                </div>
                <div className="muted-note">Editing is mocked in this prototype — no changes are persisted to BigQuery.</div>
              </div>
            )}
          </div>
        </div>

        <div className="card" style={{ marginTop: 12 }}>
          <h2>Routing map <span className="hint">error type → team → assignee → JIRA project / component</span></h2>
          <table className="mini">
            <thead><tr><th>Error type</th><th>Routed team</th><th>Default assignee</th><th>JIRA project</th><th>Component</th></tr></thead>
            <tbody>
              {data.routing.map((r, i) => (
                <tr key={i}>
                  <td>{labelFor(data.errorTypes, r.errorType)}</td><td>{r.team}</td><td>{r.assignee}</td>
                  <td className="mono">{r.project}</td><td><span className="tag">{r.component}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card" style={{ marginTop: 12 }}>
          <h2>SLA targets per severity</h2>
          <table className="mini" style={{ maxWidth: 420 }}>
            <thead><tr><th>Severity</th><th className="num">Resolution target</th></tr></thead>
            <tbody>
              {["Urgent", "High", "Medium", "Low"].map((s) => (
                <tr key={s}><td>{sevPill(s)}</td><td className="num">{data.slaTargets[s]} day{data.slaTargets[s] > 1 ? "s" : ""}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="form-row"><label>{label}</label>{children}</div>;
}
