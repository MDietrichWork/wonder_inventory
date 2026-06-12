import type { Bootstrap, Drill } from "./types";
import { countBy, movementOf, metrics, labelFor } from "./lib";
import { HBars, Trend, SystemDonut } from "./charts";

export function Dashboard({ data, drillTo }: { data: Bootstrap; drillTo: (label: string, test: Drill extends null ? never : (e: any) => boolean) => void }) {
  const exc = data.exceptions;
  const m = metrics(exc, data.meta.runDate);

  const kpis = [
    { label: "Open exceptions", val: m.open, drill: { label: "Open exceptions", test: (e: any) => e.isOpen } },
    { label: "New today", val: m.newToday, drill: { label: "New today · run " + data.meta.runDate, test: (e: any) => (e.detectedOn || e.created) === data.meta.runDate } },
    { label: "Auto-closed today", val: m.autoClosedToday, drill: { label: "Auto-closed today", test: (e: any) => e.autoClosed && e.resolved === data.meta.runDate } },
    { label: "Avg turnaround", val: m.avgTat.toFixed(1) + "d", drill: null },
    { label: "% within SLA", val: m.pctSla + "%", drill: { label: "Breaching SLA (open)", test: (e: any) => e.isOpen && !e.withinSla } },
  ];

  const byType = countBy(exc, "errorType");
  const byFac = countBy(exc, "facility");
  const byMove = countBy(exc, movementOf);

  const typeEntries = Object.entries(byType).map(([k, v]) => [labelFor(data.errorTypes, k), v, k] as [string, number, string]).sort((a, b) => b[1] - a[1]);
  const facEntries = Object.entries(byFac).map(([k, v]) => [k, v, k] as [string, number, string]).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const moveEntries = Object.entries(byMove).map(([k, v]) => [k, v, k] as [string, number, string]).sort((a, b) => b[1] - a[1]);
  const sevEntries = ["Urgent", "High", "Medium", "Low"].map((s) => [s, exc.filter((e) => e.severity === s).length, s] as [string, number, string]);

  return (
    <section className="view active">
      <div className="page-head">
        <h1>Reporting Dashboard</h1>
        <p>
          Wonder Group has no central ERP. A synthetic <b>unified inventory ledger</b> plus a <b>purchase-order (PO) table</b> in
          BigQuery serve as the sub-ledger Accounting uses to book the general ledger at month-end. Each morning a batch job validates
          the data, flags errors, auto-creates JIRA tickets routed to the right team, tracks turnaround against SLA, spots recurring
          errors, and <b>auto-closes</b> tickets once Data Engineering fixes the underlying table. Click any tile or chart to drill in.
        </p>
      </div>
      <div className="scroll-pad">
        <div className="kpi-row">
          {kpis.map((t, i) => (
            <div key={i} className={"kpi" + (t.drill ? " clickable" : "")} onClick={() => t.drill && drillTo(t.drill.label, t.drill.test as any)}>
              <div className="label">{t.label}</div>
              <div className="value">{t.val}</div>
            </div>
          ))}
        </div>

        <div className="panels">
          <div className="card">
            <h2>Error trend <span className="hint">flagged vs auto-closed / day · last 21 days</span></h2>
            <div id="trend-chart"><Trend data={data.trend} /></div>
            <div className="chart-legend">
              <span><i style={{ background: "var(--accent)" }} /> Errors flagged</span>
              <span><i style={{ background: "var(--teal)" }} /> Auto-closed</span>
            </div>
          </div>
          <div className="card">
            <h2>Errors by system of origin <span className="hint">click to drill</span></h2>
            <SystemDonut counts={countBy(exc, "system")} onDrill={(s) => drillTo("System: " + s, ((e: any) => e.system === s) as any)} />
          </div>
        </div>

        <div className="panels equal">
          <div className="card">
            <h2>Errors by type <span className="hint">click a bar to drill</span></h2>
            <div className="hbars"><HBars entries={typeEntries} onDrill={(v) => drillTo("Type: " + labelFor(data.errorTypes, v), ((e: any) => e.errorType === v) as any)} /></div>
          </div>
          <div className="card">
            <h2>Errors by facility <span className="hint">click a bar to drill</span></h2>
            <div className="hbars"><HBars entries={facEntries} onDrill={(v) => drillTo("Facility: " + v, ((e: any) => e.facility === v) as any)} /></div>
          </div>
        </div>

        <div className="panels equal">
          <div className="card">
            <h2>Errors by inventory movement type <span className="hint">click a bar to drill</span></h2>
            <div className="hbars"><HBars entries={moveEntries} onDrill={(v) => drillTo("Movement: " + v, ((e: any) => movementOf(e) === v) as any)} /></div>
          </div>
          <div className="card">
            <h2>Errors by severity</h2>
            <div className="hbars"><HBars entries={sevEntries} onDrill={(v) => drillTo("Severity: " + v, ((e: any) => e.severity === v) as any)} /></div>
          </div>
        </div>

        <div className="card">
          <h2>Daily waste over $10K by location <span className="hint">prior day · valued at consumable-unit cost · excludes implausible-qty rows (those become tickets)</span></h2>
          <div className="card-sub">Monitoring metric, not tickets — where a location's waste (Lost / Expiration / Damage / Recall) topped the daily $ threshold.</div>
          {(() => {
            const w = data.wasteByLocation || [];
            const mx = Math.max(...w.map((x) => x.dollars), 1);
            if (!w.length) return <div className="tip" style={{ padding: "16px 4px" }}>No location exceeded the daily waste threshold for {data.meta.runDate}.</div>;
            return (
              <div className="hbars">
                {w.map((x, i) => (
                  <div key={i} className="hbar" title={`${x.facility}: $${x.dollars.toLocaleString()} across ${x.skus} SKUs`}>
                    <div className="hlabel">{x.facility}</div>
                    <div className="track"><div className="fill" style={{ width: Math.round((100 * x.dollars) / mx) + "%", background: "var(--bad)" }} /></div>
                    <div className="hval">${Number(x.dollars).toLocaleString()}</div>
                  </div>
                ))}
              </div>
            );
          })()}
        </div>

        <div className="card">
          <h2>Recurring-error leaderboard <span className="hint">same fingerprint over 30 days · click to drill</span></h2>
          <div className="card-sub">Where the same defect keeps coming back — prime candidates for an upstream fix.</div>
          <div className="lb">
            {data.recurring.map((r, i) => (
              <div key={i} className="lb-row clickable" onClick={() => drillTo("Type: " + labelFor(data.errorTypes, r.errorType), ((e: any) => e.errorType === r.errorType) as any)}>
                <div className="lb-rank">{i + 1}</div>
                <div>
                  <div className="lb-title">{labelFor(data.errorTypes, r.errorType)}</div>
                  <div className="tip">{r.facility} · routed to {r.team} · last seen {r.lastSeen}</div>
                </div>
                <div className="lb-count">{r.count30d}×</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
