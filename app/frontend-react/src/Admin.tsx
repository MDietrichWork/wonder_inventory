import { useMemo, useState } from "react";
import type { Bootstrap } from "./types";
import { sevPill } from "./Workbench";
import { labelFor } from "./lib";
import { apiPatch, putThresholds, putWasteCombos } from "./api";

// A rule's live status. Two switches decide whether it actually produces tickets: the Enabled
// toggle (user-controlled) AND whether a detector query is wired into the engine (data.wired).
// Catalog-only = defined/documented + enabled, but no detector yet, so it silently finds nothing.
function ruleStatus(r: Bootstrap["rules"][number]) {
  if (!r.enabled) return { label: "Paused", cls: "rs-paused", title: "Disabled — toggled off, so it does not run." };
  if (r.wired) return { label: "Live", cls: "rs-live", title: "Enabled and a detector is wired in — runs in the daily validation job and can create tickets." };
  return { label: "Catalog-only", cls: "rs-catalog", title: "Enabled, but no detector query is wired in yet — defined and documented, but it produces no exceptions." };
}

export function statusBadge(r: Bootstrap["rules"][number]) {
  const s = ruleStatus(r);
  return <span className={"pill " + s.cls} title={s.title}><span className="rs-dot" />{s.label}</span>;
}

// Group rules by their ID family for display: the PO-* family first, then the other families
// alphabetically; within a family, numeric suffixes ascending (PO-01, PO-02, … PO-14).
function ruleSortKey(id: string): [number, string, number, string] {
  const m = id.match(/^([A-Za-z]+)-?(.*)$/);
  const prefix = m ? m[1] : id;
  const rest = m ? m[2] : "";
  const num = /^\d+$/.test(rest) ? parseInt(rest, 10) : Number.MAX_SAFE_INTEGER;
  return [prefix === "PO" ? 0 : 1, prefix, num, rest];
}

function byRuleId(a: Bootstrap["rules"][number], b: Bootstrap["rules"][number]) {
  const [ga, pa, na, ra] = ruleSortKey(a.id);
  const [gb, pb, nb, rb] = ruleSortKey(b.id);
  return ga - gb || pa.localeCompare(pb) || na - nb || ra.localeCompare(rb);
}

export function Admin({ data, refresh }: { data: Bootstrap; refresh: () => Promise<void> | void }) {
  const [selId, setSelId] = useState(data.rules[0]?.id);
  const [busyId, setBusyId] = useState<string | null>(null);
  const rule = data.rules.find((r) => r.id === selId) || data.rules[0];

  const toggleRule = async (id: string, next: boolean) => {
    setBusyId(id);
    try { await apiPatch(`/rules/${id}`, { enabled: next }); await refresh(); }
    finally { setBusyId(null); }
  };

  return (
    <section className="view active">
      <div className="page-head">
        <h1>Rule &amp; Routing Admin</h1>
        <p>The configurable layer. <b>Enabling/disabling a rule and editing its name/severity persist</b> — the next validation run honors them. Rule <i>logic</i> (the SQL) stays in code; the expression shown is the documented reference. Routing &amp; SLA cards are read-only.</p>
      </div>
      <div className="scroll-pad">
        <div className="admin-grid">
          <div className="card">
            <h2>Validation rules</h2>
            <table className="mini">
              <thead><tr><th>Rule</th><th>Error type</th><th>Type</th><th>Target table</th><th>Severity</th><th>Status</th><th className="num">Enabled</th></tr></thead>
              <tbody>
                {[...data.rules].sort(byRuleId).map((r) => (
                  <tr key={r.id} style={{ cursor: "pointer", opacity: r.enabled ? 1 : 0.5 }} onClick={() => setSelId(r.id)} className={selId === r.id ? "selected" : ""}>
                    <td className="mono"><b>{r.id}</b></td>
                    <td><b>{labelFor(data.errorTypes, r.errorType)}</b></td>
                    <td><span className="tag">{r.type}</span></td>
                    <td className="mono">{r.target}</td>
                    <td>{sevPill(r.severity)}</td>
                    <td>{statusBadge(r)}</td>
                    <td className="num">
                      <span className={"toggle" + (r.enabled ? " on" : "")} role="switch" aria-checked={r.enabled} tabIndex={0}
                        title={r.enabled ? "Enabled — click to disable" : "Disabled — click to enable"}
                        style={busyId === r.id ? { opacity: 0.4 } : undefined}
                        onClick={(ev) => { ev.stopPropagation(); if (!busyId) toggleRule(r.id, !r.enabled); }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="muted-note">Toggling persists immediately. Click a rule to load it into the editor.</div>
          </div>

          <div className="card" id="rule-editor">
            <h2>Rule editor</h2>
            {rule && <RuleEditor key={rule.id} rule={rule} data={data} refresh={refresh} />}
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

        <ThresholdEditor data={data} refresh={refresh} />

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

// Real, persisted rule editor. Mounted with key={rule.id} so fields reset when a different rule is
// selected. enabled/severity/name persist via PATCH /api/rules/{id}; the SQL is read-only (the live
// query logic is code-owned in bq_finder.py — see [[wonder-rules-in-code-not-ui]]).
function RuleEditor({ rule, data, refresh }: {
  rule: Bootstrap["rules"][number]; data: Bootstrap; refresh: () => Promise<void> | void;
}) {
  const [name, setName] = useState(rule.name);
  const [severity, setSeverity] = useState(rule.severity);
  const [enabled, setEnabled] = useState(rule.enabled);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const dirty = name !== rule.name || severity !== rule.severity || enabled !== rule.enabled;
  // Banded rules compute severity per finding from their thresholds; here it's only the catalog default.
  const banded = ["WASTE_DAILY_FACILITY", "ADJ_DAILY_FACILITY", "PO_OVER_RECEIPT"].includes(rule.errorType);
  const plain = data.errorTypes.find((t) => t.type === rule.errorType)?.plain;

  const save = async () => {
    if (!dirty) return;
    setBusy(true); setMsg(null);
    try {
      await apiPatch(`/rules/${rule.id}`, { name, severity, enabled });
      await refresh();
      setMsg("Saved. Applies on the next validation run.");
    } catch (e) { setMsg(`Save failed: ${String(e)}`); }
    finally { setBusy(false); }
  };

  return (
    <div id="rule-form">
      {plain && (
        <div style={{ marginBottom: 12, padding: "9px 11px", background: "var(--surface-3)",
                      border: "1px solid var(--line)", borderLeft: "3px solid var(--accent, #4f7cff)",
                      borderRadius: 6 }}>
          <div className="hint" style={{ marginBottom: 3 }}>What this checks</div>
          <div style={{ color: "#c8d3ec", fontSize: 12.5, lineHeight: 1.45 }}>{plain}</div>
        </div>
      )}
      <FormRow label="Rule name"><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></FormRow>
      <FormRow label="Rule ID"><input type="text" value={rule.id} readOnly /></FormRow>
      <FormRow label="Rule type"><input type="text" value={rule.type} readOnly /></FormRow>
      <FormRow label="Target table"><input type="text" value={rule.target} readOnly /></FormRow>
      <FormRow label="Maps to error"><input type="text" value={labelFor(data.errorTypes, rule.errorType)} readOnly /></FormRow>
      <FormRow label="Severity">
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          {["Urgent", "High", "Medium", "Low"].map((s) => <option key={s}>{s}</option>)}
        </select>
      </FormRow>
      {banded && <div className="muted-note">This rule computes severity per finding (banded High/Urgent by threshold) — the value above is just the catalog default.</div>}
      <FormRow label="Enabled">
        <span className={"toggle" + (enabled ? " on" : "")} role="switch" aria-checked={enabled} tabIndex={0}
          title={enabled ? "Enabled" : "Disabled"} onClick={() => setEnabled((v) => !v)} />
      </FormRow>
      <FormRow label="Reference SQL">
        <textarea rows={16} value={rule.expression} readOnly
          style={{ width: "100%", background: "var(--surface-3)", border: "1px solid var(--line)", color: "#9fb0d0", borderRadius: 6, padding: 8, fontFamily: "var(--mono)", fontSize: 11, whiteSpace: "pre" }} />
      </FormRow>
      <div className="muted-note">Read-only — the live query logic lives in <span className="mono">bq_finder.py</span>. To change $ thresholds, use the Facility threshold bands editor below.</div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 8 }}>
        <button className="btn primary sm" disabled={busy || !dirty} onClick={save}>{busy ? "Saving…" : "Save"}</button>
        {msg && <span className="tip">{msg}</span>}
      </div>
      {rule.errorType === "WASTE_DAILY_FACILITY" && <WasteComboEditor data={data} refresh={refresh} />}
    </div>
  );
}

// The editable Daily-Waste action allowlist: the (l1_action, l2_action) ledger movements that count
// as "waste" in the WASTE_DAILY_FACILITY calculation. Toggle a combo out of the calc (reversible),
// add a new one, or remove it entirely; Save writes the full set to PUT /api/waste-combos and the
// next validation run honors it. Shown inside the rule editor only for the Daily Waste rule.
type Combo = { l1Action: string; l2Action: string; enabled: boolean };
const comboKey = (c: { l1Action: string; l2Action: string }) => `${c.l1Action}||${c.l2Action}`;

function WasteComboEditor({ data, refresh }: { data: Bootstrap; refresh: () => Promise<void> | void }) {
  const original = data.wasteActionCombos || [];
  const [combos, setCombos] = useState<Combo[]>(() => original.map((c) => ({ ...c })));
  const [l1, setL1] = useState("");
  const [l2, setL2] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const origMap = useMemo(() => new Map(original.map((c) => [comboKey(c), c.enabled])), [original]);
  const curMap = new Map(combos.map((c) => [comboKey(c), c.enabled]));
  const added = combos.filter((c) => !origMap.has(comboKey(c))).length;
  const removed = [...origMap.keys()].filter((k) => !curMap.has(k)).length;
  const toggled = combos.filter((c) => origMap.has(comboKey(c)) && origMap.get(comboKey(c)) !== c.enabled).length;
  const dirty = added + removed + toggled;
  const enabledCount = combos.filter((c) => c.enabled).length;

  const toggle = (k: string) =>
    setCombos((p) => p.map((c) => (comboKey(c) === k ? { ...c, enabled: !c.enabled } : c)));
  const remove = (k: string) => setCombos((p) => p.filter((c) => comboKey(c) !== k));
  const add = () => {
    const a = l1.trim(), b = l2.trim();
    if (!a || !b) return;
    if (combos.some((c) => c.l1Action === a && c.l2Action === b)) { setMsg("That combination is already in the list."); return; }
    setCombos((p) => [...p, { l1Action: a, l2Action: b, enabled: true }]);
    setL1(""); setL2(""); setMsg(null);
  };

  const save = async () => {
    if (!dirty) return;
    setBusy(true); setMsg(null);
    try {
      const res = await putWasteCombos(combos);
      await refresh();
      setMsg(`Saved — ${res.enabled} of ${res.total} combination${res.total === 1 ? "" : "s"} in the calculation. Applies on the next validation run.`);
    } catch (e) { setMsg(`Save failed: ${String(e)}`); }
    finally { setBusy(false); }
  };

  // group by l1_action, preserving sorted order
  const groups: { l1: string; rows: Combo[] }[] = [];
  for (const c of [...combos].sort((a, b) => (a.l1Action + a.l2Action).localeCompare(b.l1Action + b.l2Action))) {
    let g = groups.find((x) => x.l1 === c.l1Action);
    if (!g) { g = { l1: c.l1Action, rows: [] }; groups.push(g); }
    g.rows.push(c);
  }

  return (
    <div style={{ marginTop: 16, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
      <h3 style={{ margin: "0 0 4px" }}>Waste action allowlist <span className="hint">which (L1 → L2) movements count as waste — editable &amp; persisted</span></h3>
      <div className="muted-note" style={{ marginBottom: 8 }}>
        The Daily Waste $ is the net over exactly these ledger <span className="mono">l1_action / l2_action</span> movements (Pavel-approved).
        Toggle one off to drop it from the calculation (reversible), or remove it entirely. <b>{enabledCount}</b> of <b>{combos.length}</b> in the calculation.
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
        <input type="text" value={l1} placeholder="L1 action (e.g. Remove)" onChange={(e) => setL1(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()} style={{ ...txt, width: 180 }} />
        <input type="text" value={l2} placeholder="L2 action (e.g. Spoiled)" onChange={(e) => setL2(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()} style={{ ...txt, width: 240 }} />
        <button className="btn sm" disabled={!l1.trim() || !l2.trim()} onClick={add}>+ Add combination</button>
      </div>

      {groups.map((g) => (
        <div key={g.l1} style={{ marginBottom: 10 }}>
          <div className="tip" style={{ marginBottom: 4 }}><b>{g.l1}</b> <span className="mono">l1_action</span> · {g.rows.length}</div>
          <table className="mini" style={{ width: 560, tableLayout: "fixed" }}>
            <thead><tr>
              <th>L2 action</th>
              <th style={{ width: 130, textAlign: "center" }}>In calculation</th>
              <th style={{ width: 90, textAlign: "center" }}>Remove</th>
            </tr></thead>
            <tbody>
              {g.rows.map((c) => {
                const k = comboKey(c);
                return (
                  <tr key={k} style={{ opacity: c.enabled ? 1 : 0.5 }}>
                    <td>{c.l2Action}</td>
                    <td style={{ textAlign: "center" }}>
                      <span className={"toggle" + (c.enabled ? " on" : "")} role="switch" aria-checked={c.enabled} tabIndex={0}
                        title={c.enabled ? "In the calculation — click to exclude" : "Excluded — click to include"}
                        onClick={() => toggle(k)} style={{ display: "inline-block", verticalAlign: "middle" }} />
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <button className="btn sm" title="Remove this combination entirely" onClick={() => remove(k)}
                        style={{ padding: "2px 10px" }}>✕</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
        <button className="btn primary sm" disabled={busy || !dirty} onClick={save}>
          {busy ? "Saving…" : dirty ? `Save ${dirty} change${dirty === 1 ? "" : "s"}` : "Save"}
        </button>
        {msg && <span className="tip">{msg}</span>}
      </div>
      <div className="muted-note">
        Toggling off persists and survives restarts; removing entirely deletes the row, but the seeded defaults are re-added on the next backend start — toggle off instead to durably exclude one. Changes take effect on the next validation run.
      </div>
    </div>
  );
}

// Real, persisted editor (unlike the mocked rule/routing cards) for the banded daily-rule $
// thresholds (Daily Waste / Daily Adjustments), per facility type. Saves to PUT /api/thresholds.
type Band = Bootstrap["thresholds"][number];
const bandKey = (b: { errorType: string; facilityType: string }) => `${b.errorType}|${b.facilityType}`;

function ThresholdEditor({ data, refresh }: { data: Bootstrap; refresh: () => Promise<void> | void }) {
  const original = data.thresholds || [];
  const [vals, setVals] = useState<Record<string, { high: number; urgent: number }>>(
    () => Object.fromEntries(original.map((b) => [bandKey(b), { high: b.high, urgent: b.urgent }]))
  );
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const set = (k: string, field: "high" | "urgent", v: number) =>
    setVals((p) => ({ ...p, [k]: { ...p[k], [field]: v } }));

  const dirty = original.filter((b) => {
    const v = vals[bandKey(b)];
    return v && (v.high !== b.high || v.urgent !== b.urgent);
  });

  const save = async () => {
    if (!dirty.length) return;
    setBusy(true); setMsg(null);
    try {
      const res = await putThresholds(dirty.map((b) => ({
        errorType: b.errorType, facilityType: b.facilityType,
        high: vals[bandKey(b)].high, urgent: vals[bandKey(b)].urgent,
      })));
      await refresh();
      setMsg(`Saved ${res.updated} threshold band${res.updated === 1 ? "" : "s"}. New values apply on the next validation run.`);
    } catch (e) {
      setMsg(`Save failed: ${String(e)}`);
    } finally { setBusy(false); }
  };

  // group bands by error type, preserving order
  const groups: { errorType: string; errorLabel: string; bands: Band[] }[] = [];
  for (const b of original) {
    let g = groups.find((x) => x.errorType === b.errorType);
    if (!g) { g = { errorType: b.errorType, errorLabel: b.errorLabel, bands: [] }; groups.push(g); }
    g.bands.push(b);
  }

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <h2>Facility threshold bands <span className="hint">High / Urgent $ per facility type — editable &amp; persisted</span></h2>
      {groups.map((g) => (
        <div key={g.errorType} style={{ marginBottom: 14 }}>
          <div className="tip" style={{ marginBottom: 4 }}><b>{g.errorLabel}</b> <span className="mono">{g.errorType}</span></div>
          <table className="mini" style={{ maxWidth: 520 }}>
            <thead><tr><th>Facility type</th><th className="num">High ≥ $</th><th className="num">Urgent ≥ $</th></tr></thead>
            <tbody>
              {g.bands.map((b) => {
                const k = bandKey(b);
                return (
                  <tr key={k}>
                    <td><span className="tag">{b.facilityType}</span></td>
                    <td className="num"><input type="number" min={0} step={50} value={vals[k]?.high ?? b.high}
                      onChange={(e) => set(k, "high", Number(e.target.value))} style={inp} /></td>
                    <td className="num"><input type="number" min={0} step={50} value={vals[k]?.urgent ?? b.urgent}
                      onChange={(e) => set(k, "urgent", Number(e.target.value))} style={inp} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 4 }}>
        <button className="btn primary sm" disabled={busy || !dirty.length} onClick={save}>
          {busy ? "Saving…" : dirty.length ? `Save ${dirty.length} change${dirty.length === 1 ? "" : "s"}` : "Save"}
        </button>
        {msg && <span className="tip">{msg}</span>}
      </div>
      <div className="muted-note">Urgent should be ≥ High. Changes persist to the database and take effect on the next validation run.</div>
    </div>
  );
}

const inp: React.CSSProperties = {
  width: 110, textAlign: "right", background: "var(--surface-3)", border: "1px solid var(--line)",
  color: "#c8d3ec", borderRadius: 6, padding: "4px 8px", fontFamily: "var(--mono)", fontSize: 12,
};

const txt: React.CSSProperties = {
  background: "var(--surface-3)", border: "1px solid var(--line)", color: "#c8d3ec",
  borderRadius: 6, padding: "5px 8px", fontSize: 12,
};
