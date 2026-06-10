import { useEffect, useState, Fragment } from "react";
import type { Bootstrap, Exception } from "./types";
import { fmtNum } from "./lib";
import { getBreakdown, jiraUrl, apiPost } from "./api";
import { sevPill, statusPill } from "./Workbench";

const SNAP_HIDE = new Set(["tolerance_pct", "uom_match", "status", "ordered_uom", "received_uom", "breached_at", "first_receipt", "last_receipt"]);
const STATUS_OPTS = ["Open", "In Progress", "In Review", "Resolved"];

function snapValue(k: string, val: any, snap: Record<string, any>): { text: string; neg: boolean } {
  let out: any = val;
  if (k === "ordered_qty" && snap.ordered_uom) out = fmtNum(val) + " " + snap.ordered_uom;
  else if (k === "received_qty" && snap.received_uom) out = fmtNum(val) + " " + snap.received_uom;
  else if (k === "over_by_pct" && val != null) out = fmtNum(val) + "%";
  else if (k === "supplier_price") out = val == null ? null : "$" + Number(val).toFixed(2);
  const neg = (typeof out === "number" && out < 0) || out === null;
  return { text: out === null ? "NULL" : String(out), neg };
}

export function Drawer({ data, exc, onClose, refresh }: {
  data: Bootstrap; exc: Exception; onClose: () => void; refresh: () => Promise<void>;
}) {
  const notes = exc.notes || [];
  const rule = data.rules.find((r) => r.id === exc.rule);
  const meta = data.errorTypes.find((t) => t.type === exc.errorType);
  const route = data.routing.find((r) => r.errorType === exc.errorType);
  const snap = exc.snapshot || {};
  const [bd, setBd] = useState<any>(null);
  const [noteText, setNoteText] = useState("");
  const isReceipt = exc.errorType === "PO_OVER_RECEIPT" || exc.errorType === "PO_IMPLAUSIBLE_QTY";

  useEffect(() => {
    setBd(null);
    if (isReceipt) getBreakdown(exc.pk).then(setBd).catch(() => setBd({ available: false }));
  }, [exc.pk]);

  const since: string[] = [];
  if (exc.created) since.push("began " + exc.created);
  if (exc.detectedOn && exc.detectedOn !== exc.created) since.push("detected " + exc.detectedOn);
  if (exc.lastReceipt) since.push("last receipt " + exc.lastReceipt);

  const jira = jiraUrl(data.meta, exc.jira);
  const handed = !!(exc.currentHolder && exc.currentHolder !== exc.primaryOwner);

  const act = async (path: string, body?: any) => { await apiPost(`/exceptions/${exc.pk}${path}`, body); await refresh(); };
  const changeStatus = (to: string) => { if (to !== exc.jiraStatus) act("/transition", { to }); };
  const reassign = () => { const w = prompt(`Reassign the PRIMARY OWNER of ${exc.id} (accountability moves to this person, updates the Jira assignee):`, exc.primaryOwner); if (w) act("/assign", { assignee: w }); };
  const handoff = () => {
    const p = prompt(`Hand off ${exc.id} to which person? (they do the work; ${exc.primaryOwner} stays accountable, SLA doesn't reset)`, exc.subAssign?.toPerson || "");
    if (!p) return;
    const t = prompt("Their team (optional):", exc.subAssign?.toTeam || "");
    act("/subassign", { person: p, team: t || null });
  };
  const submitNote = async () => { if (!noteText.trim()) return; await act("/comment", { text: noteText.trim() }); setNoteText(""); };

  const statusOpts = STATUS_OPTS.includes(exc.jiraStatus) ? STATUS_OPTS : [exc.jiraStatus, ...STATUS_OPTS];

  return (
    <>
      <div className="drawer-scrim show" onClick={onClose} />
      <aside className="drawer show" role="dialog" aria-label="Exception detail">
        <div className="drawer-head">
          <div>
            <div className="drawer-title">{exc.id} · {exc.errorType}</div>
            <div className="drawer-sub">
              {sevPill(exc.severity)}{statusPill(exc.jiraStatus)}
              <span className="tag">{exc.facility} · {exc.system}</span>
              {jira ? <a className="jira-link" href={jira} target="_blank">{exc.jira}</a> : <span className="tip">{exc.jira}</span>}
              <span className="tip">Age {exc.age}d / {exc.slaTarget}d SLA · {exc.withinSla ? "within SLA" : "BREACHING"}</span>
              {since.length > 0 && <span className="tip">{since.join(" · ")}</span>}
            </div>
          </div>
          <button className="btn ghost sm x" onClick={onClose}>✕ Esc</button>
        </div>

        <div className="drawer-body">
          {/* Offending snapshot */}
          <div className="section">
            <h3>Offending {exc.table} snapshot</h3>
            <div className="kv">
              {Object.keys(snap).filter((k) => !SNAP_HIDE.has(k)).map((k) => {
                const { text, neg } = snapValue(k, snap[k], snap);
                return <Fragment key={k}><div className="k">{k}</div><div className={"v" + (neg ? " neg" : "")}>{text}</div></Fragment>;
              })}
            </div>
          </div>

          {/* Why this flagged — full breakdown */}
          {isReceipt && (
            <div className="section">
              <h3>Why this flagged — contributing records</h3>
              <Breakdown bd={bd} />
            </div>
          )}

          {/* Ownership & assignment */}
          <div className="section">
            <h3>Ownership &amp; assignment</h3>
            <div className="kv">
              <div className="k">primary_owner</div><div className="v">{exc.primaryOwner}  (accountable)</div>
              <div className="k">currently_with</div><div className="v">{exc.currentHolder} · held {exc.heldDays}d (since {exc.heldSince})</div>
              <div className="k">jira_project</div><div className="v">{route?.project || "WIQ"}</div>
              <div className="k">recurrence_30d</div><div className="v">×{exc.recurrence}</div>
            </div>
            {handed && exc.subAssign ? (
              <div className="subassign-box">
                <div className="sa-head">↳ Handed off to <b>{exc.subAssign.toPerson}{exc.subAssign.toTeam ? " · " + exc.subAssign.toTeam : ""}</b></div>
                <div className="tip">By {exc.primaryOwner} on {(exc.subAssign.at || "").replace("T", " ").replace("Z", " UTC")} — {exc.primaryOwner} stays primary owner (accountable).</div>
                <div className="sa-sla">SLA does not reset · current holder {exc.currentHolder} has had it {exc.heldDays} day(s)</div>
              </div>
            ) : (
              <div className="tip" style={{ marginTop: 8 }}>Held by the primary owner. Use “Hand off…” to give the work to someone else while staying accountable (SLA doesn’t reset).</div>
            )}
          </div>

          {/* Timeline */}
          <div className="section">
            <h3>JIRA &amp; ownership timeline · {exc.jira}</h3>
            <ul className="timeline">
              {exc.timeline.map((t, i) => {
                const auto = /auto/i.test(t.status) || t.by === "batch-validator";
                const handoff = /sub-assigned|handed off/i.test(t.status);
                return (
                  <li key={i} className={auto ? "auto" : handoff ? "handoff" : ""}>
                    <span className="tdot" />
                    <div className="tstatus">{t.status}</div>
                    <div className="tmeta">{t.at.replace("T", " ").replace("Z", " UTC")} · {t.by}</div>
                  </li>
                );
              })}
            </ul>
            {exc.autoClosed && <div className="tip">✔ <b style={{ color: "var(--ok)" }}>Auto-closed</b> — this issue did not reproduce on the {data.meta.runDate} run after the underlying table was fixed.</div>}
          </div>

          {/* Notes */}
          <div className="section">
            <h3>Notes</h3>
            <ul className="notes">
              {notes.length === 0 && <div className="tip">No notes yet.</div>}
              {notes.map((n, i) => (
                <li key={i} className="note"><div className="nm">{n.by} · {n.at}</div><div>{n.text}</div></li>
              ))}
            </ul>
            <div className="note-input">
              <input type="text" placeholder="Add a note (posts a comment to Jira)…" value={noteText}
                onChange={(e) => setNoteText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && submitNote()} />
              <button className="btn sm primary" onClick={submitNote}>Add</button>
            </div>
          </div>

          {/* Validation rule — last */}
          <div className="section">
            <h3>Validation rule that fired</h3>
            <div className="rule-box">
              <div className="rname">{(rule?.name || exc.errorType) + "  —  " + (rule?.type || meta?.ruleType || "")}</div>
              <div className="tip">{meta?.desc || ""}</div>
              <code>{rule?.expression || "(rule expression unavailable)"}</code>
            </div>
          </div>
        </div>

        {/* Action footer */}
        <div className="drawer-actions">
          <label className="dr-statuswrap">Status
            <select className="dr-status" value={exc.jiraStatus} onChange={(e) => changeStatus(e.target.value)}>
              {statusOpts.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          {jira && <a className="btn primary sm" href={jira} target="_blank">Open in JIRA ↗</a>}
          <button className="btn sm" onClick={reassign}>Reassign owner</button>
          <button className="btn sm" onClick={handoff}>Hand off…</button>
          <button className="btn sm" onClick={() => document.querySelector<HTMLInputElement>(".note-input input")?.focus()}>Add note</button>
        </div>
      </aside>
    </>
  );
}

function Breakdown({ bd }: { bd: any }) {
  if (!bd) return <div className="tip">Loading the PO line and ledger receipts…</div>;
  if (!bd.available) return <div className="tip">{bd.error ? "Breakdown unavailable: " + bd.error : "Live record breakdown is available when connected to BigQuery."}</div>;
  return (
    <>
      <div className="tip" style={{ marginBottom: 8 }}>
        Ordered {fmtNum(bd.ordered_qty)} {bd.ordered_uom || ""} · received {fmtNum(bd.received_qty)} {bd.received_uom || ""} ({bd.over_by_pct}% over) · {bd.ledger_count} ledger receipt(s)
      </div>
      {bd.uom_match === false && <div className="dup-warn">⚠ Unit-of-measure mismatch — ordered in {bd.ordered_uom || "?"} but received in {bd.received_uom || "?"}. The over-receipt % may be apples-to-oranges until reconciled.</div>}
      {bd.duplicate_suspected && <div className="dup-warn">⚠ Possible duplicate receipt — multiple identical Add / PO Receipt events. Inventory was added (l1 = Add), not adjusted out, so the receipt looks double-logged.</div>}
      <table className="mini">
        <thead><tr><th>Source</th><th className="num">Qty</th><th>UoM</th><th>Type / action</th><th>Facility</th><th>When</th></tr></thead>
        <tbody>
          {(bd.rows || []).map((r: any, i: number) => (
            <tr key={i} className={r.source === "PO" ? "bd-po" : ""}>
              <td><span className="tag">{r.source}</span></td>
              <td className="num">{fmtNum(r.qty)}</td>
              <td>{r.uom || "—"}</td>
              <td>{r.source === "PO" ? (r.order_type || "—") : (r.l1_action || "") + (r.l2_action ? " / " + r.l2_action : "")}</td>
              <td>{r.facility || "—"}</td>
              <td className="mono" style={{ fontSize: 11 }}>{r.ts ? r.ts.replace("T", " ").slice(0, 19) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
