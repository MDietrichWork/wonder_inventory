import type { Bootstrap, Exception } from "./types";
import { sevPill } from "./Workbench";

export function Sla({ data, drillTo, ownerQueue, openExc }: {
  data: Bootstrap;
  drillTo: (label: string, test: (e: Exception) => boolean) => void;
  ownerQueue: (name: string) => void;
  openExc: (pk: number) => void;
}) {
  const exc = data.exceptions;
  const open = exc.filter((e) => e.isOpen);

  const buckets: [string, (a: number) => boolean][] = [
    ["0–1 day", (a) => a <= 1], ["1–3 days", (a) => a > 1 && a <= 3],
    ["3–7 days", (a) => a > 3 && a <= 7], ["7+ days", (a) => a > 7],
  ];

  // By team
  const teamRows = Object.keys(data.teams).map((team) => {
    const all = exc.filter((e) => e.team === team);
    const openT = all.filter((e) => e.isOpen);
    const resolved = all.filter((e) => e.turnaround != null);
    const avg = resolved.length ? resolved.reduce((s, e) => s + (e.turnaround || 0), 0) / resolved.length : null;
    const within = all.filter((e) => (e.isOpen ? e.age <= e.slaTarget : e.withinSla)).length;
    const breaching = all.length - within;
    const pct = all.length ? Math.round((100 * within) / all.length) : 0;
    return { team, total: all.length, open: openT.length, avg, within, breaching, pct };
  }).filter((r) => r.total > 0);

  // By owner (accountable, includes handed-off)
  const owners: Record<string, Exception[]> = {};
  exc.forEach((e) => { if (e.primaryOwner) (owners[e.primaryOwner] = owners[e.primaryOwner] || []).push(e); });
  const ownerRows = Object.entries(owners).map(([name, theirs]) => {
    const openP = theirs.filter((e) => e.isOpen);
    const handed = openP.filter((e) => e.currentHolder && e.currentHolder !== name).length;
    const breach = openP.filter((e) => !e.withinSla).length;
    const avgAge = openP.length ? openP.reduce((s, e) => s + e.age, 0) / openP.length : null;
    return { name, team: theirs[0].team, open: openP.length, handed, breach, avgAge };
  }).sort((a, b) => b.breach - a.breach || (b.avgAge || 0) - (a.avgAge || 0));

  // By holder (active work)
  const holders: Record<string, Exception[]> = {};
  open.forEach((e) => { const h = e.currentHolder || e.primaryOwner; if (h) (holders[h] = holders[h] || []).push(e); });
  const holderRows = Object.entries(holders).map(([name, held]) => {
    const handedToThem = held.filter((e) => e.primaryOwner && e.primaryOwner !== name).length;
    const breach = held.filter((e) => !e.withinSla).length;
    const totalHeld = held.reduce((s, e) => s + (e.heldDays || 0), 0);
    return { name, holding: held.length, handedToThem, breach, avgHeld: held.length ? totalHeld / held.length : 0, totalHeld };
  }).sort((a, b) => b.totalHeld - a.totalHeld || b.holding - a.holding);

  const overdue = open.filter((e) => !e.withinSla).sort((a, b) => (b.age - b.slaTarget) - (a.age - a.slaTarget));

  return (
    <section className="view active">
      <div className="page-head">
        <h1>Ticket Turnaround / SLA</h1>
        <p>Resolution performance per team and per person, aging of open tickets, and who is falling behind on SLA targets. Sub-assigned work keeps its original SLA — time is attributed to whoever currently holds it.</p>
      </div>
      <div className="scroll-pad">
        <h2 style={{ fontSize: 12, color: "var(--text-faint)", textTransform: "uppercase", letterSpacing: ".7px", margin: "0 0 10px" }}>Open ticket aging</h2>
        <div className="buckets">
          {buckets.map(([label, test], i) => (
            <div key={i} className={"bucket b" + i}>
              <div className="bk-label">{label}</div>
              <div className="bk-val">{open.filter((e) => test(e.age)).length}</div>
              <div className="tip">open tickets</div>
            </div>
          ))}
        </div>

        <div className="panels equal">
          <div className="card">
            <h2>By team <span className="hint">avg turnaround &amp; SLA compliance</span></h2>
            <table className="mini">
              <thead><tr><th>Team</th><th className="num">Open</th><th className="num">Avg turnaround</th><th className="num">Within SLA</th><th className="num">Breaching</th><th className="num">% within</th></tr></thead>
              <tbody>
                {teamRows.map((r) => (
                  <tr key={r.team}>
                    <td><b>{r.team}</b></td>
                    <td className="num">{r.open}</td>
                    <td className="num">{r.avg == null ? "—" : r.avg.toFixed(1) + "d"}</td>
                    <td className="num">{r.within}</td>
                    <td className="num"><span className={r.breaching > 0 ? "sla-bad" : ""}>{r.breaching}</span></td>
                    <td className="num"><span className={r.pct >= 90 ? "sla-ok" : "sla-bad"}>{r.pct}%</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card">
            <h2>By owner <span className="hint">accountable · click a name for their queue</span></h2>
            <table className="mini">
              <thead><tr><th>Primary owner</th><th>Team</th><th className="num">Open</th><th className="num">Handed off</th><th className="num">Breaching</th><th className="num">Avg age (open)</th></tr></thead>
              <tbody>
                {ownerRows.map((r) => (
                  <tr key={r.name} className="clickrow" onClick={() => ownerQueue(r.name)} title={`Open ${r.name}'s accountability queue`}>
                    <td><b className={r.breach > 0 ? "behind" : ""}>{r.name}</b></td>
                    <td>{r.team}</td>
                    <td className="num">{r.open}</td>
                    <td className="num">{r.handed ? <span className="subtag">↳ {r.handed}</span> : "—"}</td>
                    <td className="num"><span className={r.breach > 0 ? "sla-bad" : ""}>{r.breach}</span></td>
                    <td className="num">{r.avgAge == null ? "—" : r.avgAge.toFixed(1) + "d"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="muted-note">Accountability stays with the primary owner even after a hand-off — these counts include handed-off tickets.</div>
          </div>
        </div>

        <div className="card">
          <h2>By holder <span className="hint">who is actively doing the work now · held-time attributed to the current holder · click to drill</span></h2>
          <table className="mini">
            <thead><tr><th>Current holder</th><th className="num">Holding</th><th className="num">Handed to them</th><th className="num">Breaching</th><th className="num">Avg held</th><th className="num">Total held-days</th></tr></thead>
            <tbody>
              {holderRows.map((r) => (
                <tr key={r.name} className="clickrow" onClick={() => drillTo("Currently held by: " + r.name, (e) => e.isOpen && (e.currentHolder || e.primaryOwner) === r.name)}>
                  <td><b>{r.name}</b></td>
                  <td className="num">{r.holding}</td>
                  <td className="num">{r.handedToThem ? <span className="subtag">↳ {r.handedToThem}</span> : "—"}</td>
                  <td className="num"><span className={r.breach > 0 ? "sla-bad" : ""}>{r.breach}</span></td>
                  <td className="num">{r.avgHeld.toFixed(1)}d</td>
                  <td className="num">{r.totalHeld}d</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted-note">A handed-off ticket appears under its holder here, but the SLA clock still belongs to the primary owner and does not reset.</div>
        </div>

        <div className="card">
          <h2>Overdue open tickets <span className="hint">age exceeds severity SLA target</span></h2>
          <table className="mini">
            <thead><tr><th>Error ID</th><th>JIRA</th><th>Type</th><th>Severity</th><th>Assignee</th><th>Sub-assigned to</th><th className="num">Age</th><th className="num">SLA</th><th className="num">Over by</th></tr></thead>
            <tbody>
              {overdue.map((e) => (
                <tr key={e.pk} style={{ cursor: "pointer" }} onClick={() => openExc(e.pk)}>
                  <td className="mono">{e.id}</td>
                  <td><a className="jira-link" href="#" onClick={(ev) => ev.preventDefault()}>{e.jira}</a></td>
                  <td>{e.errorType}</td>
                  <td>{sevPill(e.severity)}</td>
                  <td>{e.primaryOwner}</td>
                  <td>{e.subAssign ? <span className="subtag">↳ {e.subAssign.toTeam}</span> : "—"}</td>
                  <td className="num">{e.age}d</td>
                  <td className="num">{e.slaTarget}d</td>
                  <td className="num"><span className="sla-bad">+{e.age - e.slaTarget}d</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
