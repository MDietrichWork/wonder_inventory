import { useEffect, useState, Fragment } from "react";
import type { Bootstrap, Exception } from "./types";
import { fmtNum } from "./lib";
import { getBreakdown, jiraUrl } from "./api";
import { sevPill, statusPill } from "./Workbench";

const SNAP_HIDE = new Set(["tolerance_pct", "uom_match", "status", "ordered_uom", "received_uom", "breached_at", "first_receipt", "last_receipt"]);

function snapValue(k: string, val: any, snap: Record<string, any>): { text: string; neg: boolean } {
  let out: any = val;
  if (k === "ordered_qty" && snap.ordered_uom) out = fmtNum(val) + " " + snap.ordered_uom;
  else if (k === "received_qty" && snap.received_uom) out = fmtNum(val) + " " + snap.received_uom;
  else if (k === "over_by_pct" && val != null) out = fmtNum(val) + "%";
  else if (k === "supplier_price") out = val == null ? null : "$" + Number(val).toFixed(2);
  const neg = (typeof out === "number" && out < 0) || out === null;
  return { text: out === null ? "NULL" : String(out), neg };
}

export function Drawer({ data, exc, onClose }: { data: Bootstrap; exc: Exception; onClose: () => void }) {
  const rule = data.rules.find((r) => r.id === exc.rule);
  const meta = data.errorTypes.find((t) => t.type === exc.errorType);
  const snap = exc.snapshot || {};
  const [bd, setBd] = useState<any>(null);
  const isReceipt = exc.errorType === "PO_OVER_RECEIPT" || exc.errorType === "PO_IMPLAUSIBLE_QTY";

  useEffect(() => {
    setBd(null);
    if (isReceipt) getBreakdown(exc.pk).then(setBd).catch(() => setBd({ available: false }));
  }, [exc.pk]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const since: string[] = [];
  if (exc.created) since.push("began " + exc.created);
  if (exc.detectedOn && exc.detectedOn !== exc.created) since.push("detected " + exc.detectedOn);
  if (exc.lastReceipt) since.push("last receipt " + exc.lastReceipt);

  const jira = jiraUrl(data.meta, exc.jira);
  const handed = exc.currentHolder && exc.currentHolder !== exc.primaryOwner;

  return (
    <>
      <div className="drawer-scrim show" onClick={onClose} />
      <aside className="drawer open" role="dialog" aria-label="Exception detail">
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
          <div className="section">
            <h3>Offending {exc.table} snapshot</h3>
            <div className="kv">
              {Object.keys(snap).filter((k) => !SNAP_HIDE.has(k)).map((k) => {
                const { text, neg } = snapValue(k, snap[k], snap);
                return <Fragment key={k}><div className="k">{k}</div><div className={"v" + (neg ? " neg" : "")}>{text}</div></Fragment>;
              })}
            </div>
          </div>

          {isReceipt && (
            <div className="section">
              <h3>Why this flagged — contributing records</h3>
              {!bd ? <div className="tip">Loading the PO line and ledger receipts…</div>
                : bd.available ? <div className="tip">Ordered {fmtNum(bd.ordered_qty)} {bd.ordered_uom} vs received {fmtNum(bd.received_qty)} {bd.received_uom} across {bd.ledger_count} ledger events{bd.duplicate_suspected ? " · duplicate receipt suspected" : ""}.</div>
                : <div className="tip">Breakdown unavailable.</div>}
            </div>
          )}

          <div className="section">
            <h3>Ownership &amp; assignment</h3>
            <div className="kv">
              <div className="k">primary_owner</div><div className="v">{exc.primaryOwner}  (accountable)</div>
              <div className="k">routed_team</div><div className="v">{exc.team}</div>
              <div className="k">currently_with</div><div className="v">{exc.currentHolder} · held {exc.heldDays}d (since {exc.heldSince})</div>
            </div>
            {handed && exc.subAssign && (
              <div className="sa-note">
                <div className="tip">By {exc.primaryOwner} — stays primary owner (accountable).</div>
                <div className="sa-sla">SLA does not reset · current holder {exc.currentHolder} has had it {exc.heldDays} day(s)</div>
              </div>
            )}
          </div>

          <div className="section">
            <h3>JIRA &amp; ownership timeline{exc.jira !== "—" ? " · " + exc.jira : ""}</h3>
            <div className="timeline">
              {exc.timeline.map((t, i) => (
                <div key={i} className="tl-row">
                  <div className="tl-dot" />
                  <div><b>{t.status}</b> <span className="tip">{t.at?.replace("T", " ").replace("Z", " UTC")} · {t.by}</span></div>
                </div>
              ))}
            </div>
          </div>

          <div className="section">
            <h3>Validation rule that fired</h3>
            <div className="rule-box">
              <div className="rname">{(rule?.name || exc.errorType) + "  —  " + (rule?.type || meta?.ruleType || "")}</div>
              <div className="tip">{meta?.desc || ""}</div>
              <code>{rule?.expression || "(rule expression unavailable)"}</code>
            </div>
          </div>

          <div className="section">
            <div className="tip">Write actions (status change, reassign, hand-off, resolve) are wired in the vanilla console and port next.</div>
          </div>
        </div>
      </aside>
    </>
  );
}
