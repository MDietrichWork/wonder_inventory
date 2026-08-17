import { useEffect, useState, Fragment } from "react";
import type { Bootstrap, Exception } from "./types";
import { fmtNum, humanizeKey } from "./lib";
import { getBreakdown, getTransferBreakdown, jiraUrl, apiPost } from "./api";
import { sevPill, statusPill } from "./Workbench";

const SNAP_HIDE = new Set(["tolerance_pct", "uom_match", "status", "ordered_uom", "received_uom", "breached_at", "first_receipt", "last_receipt", "consumable_uom", "resolution"]);
const STATUS_OPTS = ["Open", "In Progress", "In Review", "Resolved"];

function fmtVal(v: any, unit?: string): string {
  if (v == null) return "—";
  if (unit === "$") return "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return fmtNum(v) + (unit ? " " + unit : "");
}

function snapValue(k: string, val: any, snap: Record<string, any>): { text: string; neg: boolean } {
  let out: any = val;
  if (k === "ordered_qty" && snap.ordered_uom) out = fmtNum(val) + " " + snap.ordered_uom;
  else if (k === "received_qty" && snap.received_uom) out = fmtNum(val) + " " + snap.received_uom;
  else if (k === "waste_qty") out = fmtNum(val) + (snap.consumable_uom ? " " + snap.consumable_uom : "");
  else if (k === "over_by_pct" && val != null) out = fmtNum(val) + "%";
  else if (k === "supplier_price") out = val == null ? null : "$" + Number(val).toFixed(2);
  else if (k === "unit_cost") out = val == null ? null : "$" + Number(val).toFixed(4);
  else if (k === "est_value") out = val == null ? null : "$" + Number(val).toLocaleString("en-US", { maximumFractionDigits: 2 });
  const neg = (typeof out === "number" && out < 0) || out === null;
  return { text: out === null ? "NULL" : String(out), neg };
}

export function Drawer({ data, exc, onClose, refresh }: {
  data: Bootstrap; exc: Exception; onClose: () => void; refresh: () => Promise<void>;
}) {
  const notes = exc.notes || [];
  const meta = data.errorTypes.find((t) => t.type === exc.errorType);
  const snap = exc.snapshot || {};
  const [bd, setBd] = useState<any>(null);
  const [xbd, setXbd] = useState<any>(null);
  const [noteText, setNoteText] = useState("");
  const isReceipt = exc.errorType === "PO_OVER_RECEIPT" || exc.errorType === "PO_IMPLAUSIBLE_QTY";
  const isXfer = exc.rule.startsWith("XFER");

  useEffect(() => {
    setBd(null);
    if (isReceipt) getBreakdown(exc.pk).then(setBd).catch(() => setBd({ available: false }));
  }, [exc.pk]);

  useEffect(() => {
    setXbd(null);
    if (isXfer) getTransferBreakdown(exc.pk).then(setXbd).catch(() => setXbd({ available: false }));
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
      <aside className={"drawer show" + (isXfer ? " drawer-xfer" : "")} role="dialog" aria-label="Exception detail">
        <div className="drawer-head">
          <div>
            <div className="drawer-title">{exc.id} · {meta?.label || exc.errorType}</div>
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
            <h3>Offending {humanizeKey(exc.table)} snapshot</h3>
            <div className="kv">
              {Object.keys(snap).filter((k) => !SNAP_HIDE.has(k)).map((k) => {
                const { text, neg } = snapValue(k, snap[k], snap);
                return <Fragment key={k}><div className="k">{humanizeKey(k)}</div><div className={"v" + (neg ? " neg" : "")}>{text}</div></Fragment>;
              })}
            </div>
          </div>

          {/* Correction applied — what the data looks like now that it auto-closed */}
          {snap.resolution && (
            <div className="section">
              <h3>✔ Correction applied{exc.resolved ? " · resolved " + exc.resolved : ""}</h3>
              <div className="tip" style={{ marginBottom: 8 }}>{snap.resolution.summary}</div>
              {(snap.resolution.fields || []).length > 0 && (
                <table className="mini">
                  <thead><tr><th>Field</th><th className="num">Was (flagged)</th><th className="num">Now (corrected)</th></tr></thead>
                  <tbody>
                    {snap.resolution.fields.map((f: any, i: number) => (
                      <tr key={i}>
                        <td>{humanizeKey(f.label)}</td>
                        <td className="num neg">{fmtVal(f.was, f.unit)}</td>
                        <td className="num ok">{fmtVal(f.now, f.unit)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Why this flagged — full breakdown */}
          {isReceipt && (
            <div className="section">
              <h3>Why this flagged — contributing records</h3>
              <Breakdown bd={bd} />
            </div>
          )}

          {/* Transfer order comparison — every Out row, then every In row */}
          {isXfer && (
            <div className="section">
              <h3>Transfer order comparison — Out vs In</h3>
              <TransferBreakdown bd={xbd} />
            </div>
          )}

          {/* Ownership & assignment */}
          <div className="section">
            <h3>Ownership &amp; assignment</h3>
            <div className="kv">
              <div className="k">Primary Owner</div><div className="v">{exc.primaryOwner}  (accountable)</div>
              <div className="k">Currently With</div><div className="v">{exc.currentHolder} · held {exc.heldDays}d (since {exc.heldSince})</div>
              <div className="k">Recurrence (30d)</div><div className="v">×{exc.recurrence}</div>
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
  if (!bd) return <div className="tip">Loading the PO line and every ledger movement on it…</div>;
  if (!bd.available) return <div className="tip">{bd.error ? "Breakdown unavailable: " + bd.error : "Live record breakdown is available when connected to BigQuery."}</div>;
  const rows = bd.rows || [];
  const ledger = rows.filter((r: any) => r.source === "LEDGER");
  const ruom = bd.received_uom || (ledger[0] && ledger[0].uom) || "";
  // running net of every PO-tagged movement (positive receipts + negative corrections) — the last
  // value lands on the flagged received_qty, so the user can trace exactly how we got to the total.
  let net = 0;
  return (
    <>
      <div className="tip" style={{ marginBottom: 8 }}>
        Ordered {fmtNum(bd.ordered_qty)} {bd.ordered_uom || ""} · received {fmtNum(bd.received_qty)} {bd.received_uom || ""} ({bd.over_by_pct}% over) — netted from {bd.ledger_count} ledger movement{bd.ledger_count === 1 ? "" : "s"} on this PO.
      </div>
      {bd.uom_match === false && <div className="dup-warn">⚠ Unit-of-measure mismatch — ordered in {bd.ordered_uom || "?"} but received in {bd.received_uom || "?"}. The over-receipt % may be apples-to-oranges until reconciled.</div>}
      {bd.duplicate_suspected && <div className="dup-warn">⚠ Possible duplicate receipt — multiple identical Add / PO Receipt events. Inventory was added (l1 = Add), not adjusted out, so the receipt looks double-logged.</div>}
      <table className="mini">
        <thead><tr><th>Source</th><th className="num">Qty</th><th>UoM</th><th>Type / action</th><th>Facility</th><th>When</th><th className="num">Net to date</th></tr></thead>
        <tbody>
          {rows.map((r: any, i: number) => {
            const isLed = r.source === "LEDGER";
            const q = Number(r.qty) || 0;
            if (isLed) net += q;
            return (
              <tr key={i} className={r.source === "PO" ? "bd-po" : ""}>
                <td><span className="tag">{r.source}</span></td>
                <td className={"num" + (q < 0 ? " neg" : "")}>{fmtNum(r.qty)}</td>
                <td>{r.uom || "—"}</td>
                <td>{r.source === "PO" ? (r.order_type || "—") : (r.l1_action || "") + (r.l2_action ? " / " + r.l2_action : "")}</td>
                <td>{r.facility || "—"}</td>
                <td className="mono" style={{ fontSize: 11 }}>{r.ts ? r.ts.replace("T", " ").slice(0, 19) : "—"}</td>
                <td className="num">{isLed ? fmtNum(net) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="bd-total">
            <td colSpan={6}>Net received against this PO line — the flagged total</td>
            <td className="num">{fmtNum(bd.received_qty)}{ruom ? " " + ruom : ""}</td>
          </tr>
        </tfoot>
      </table>
    </>
  );
}

function TransferBreakdown({ bd }: { bd: any }) {
  if (!bd) return <div className="tip">Loading everything picked (Out) and received (In) against this transfer order…</div>;
  if (!bd.available) return <div className="tip">{bd.error ? "Transfer breakdown unavailable: " + bd.error : "Live record breakdown is available when connected to BigQuery."}</div>;
  const rows = bd.rows || [];
  if (rows.length === 0) return <div className="tip">No Transfer Out / Transfer In / Received ledger activity found for transfer order {bd.transfer_order}.</div>;
  return (
    <>
      <div className="tip" style={{ marginBottom: 8 }}>
        Transfer order <span className="mono">{bd.transfer_order}</span> — {bd.out_count} Out row{bd.out_count === 1 ? "" : "s"}, {bd.in_count} In row{bd.in_count === 1 ? "" : "s"}, every Out row listed before every In row.
      </div>
      <table className="mini">
        <thead><tr><th>Leg</th><th>Item</th><th className="num">Qty</th><th>UoM</th><th>Facility</th><th>System</th><th>Movement</th><th>When</th></tr></thead>
        <tbody>
          {rows.map((r: any, i: number) => {
            const q = Number(r.qty) || 0;
            const prevLeg = i > 0 ? rows[i - 1].leg : r.leg;
            return (
              <Fragment key={i}>
                {i > 0 && r.leg !== prevLeg && <tr className="bd-total"><td colSpan={8}>↓ In — received against this transfer order</td></tr>}
                <tr>
                  <td><span className={"tag" + (r.leg === "OUT" ? " neg" : " ok")}>{r.leg}</span></td>
                  <td>{r.item_name || r.consumable_sku || "—"}</td>
                  <td className={"num" + (q < 0 ? " neg" : "")}>{fmtNum(r.qty)}</td>
                  <td>{r.uom || "—"}</td>
                  <td>{r.facility || "—"}</td>
                  <td>{r.system || "—"}</td>
                  <td>{r.movement || "—"}</td>
                  <td className="mono" style={{ fontSize: 11 }}>{r.ts ? r.ts.replace("T", " ").slice(0, 19) : "—"}</td>
                </tr>
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
