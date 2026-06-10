import { useEffect, useState, useCallback } from "react";
import type { Bootstrap, Drill, Exception } from "./types";
import { getBootstrap, apiPost } from "./api";
import { metrics } from "./lib";
import { Dashboard } from "./Dashboard";
import { Workbench } from "./Workbench";
import { Drawer } from "./Drawer";
import { Sla } from "./Sla";
import { Admin } from "./Admin";

type View = "dashboard" | "workbench" | "sla" | "admin";

export function App() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<View>("dashboard");
  const [drill, setDrill] = useState<Drill>(null);
  const [openPk, setOpenPk] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setData(await getBootstrap()); } catch (e) { setErr(String(e)); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const drillTo = (label: string, test: (e: Exception) => boolean) => { setDrill({ label, test }); setView("workbench"); };
  const ownerQueue = (name: string) => drillTo("Primary owner: " + name, (e) => e.primaryOwner === name);
  const openExc = (pk: number) => { setView("workbench"); setOpenPk(pk); };

  const runAction = async (label: string, path: string) => {
    setBusy(label);
    try { await apiPost(path); await load(); } finally { setBusy(null); }
  };

  // keyboard: 1-4 switch views, / focus search, Esc close drawer
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && t.matches && t.matches("input,select,textarea")) { if (e.key === "Escape") (t as HTMLInputElement).blur(); return; }
      if (e.key === "Escape") { setOpenPk(null); return; }
      if (e.key === "/") { e.preventDefault(); setView("workbench"); setTimeout(() => document.querySelector<HTMLInputElement>(".toolbar input[type=search]")?.focus(), 0); return; }
      const idx = ["1", "2", "3", "4"].indexOf(e.key);
      if (idx > -1) setView((["dashboard", "workbench", "sla", "admin"] as View[])[idx]);
    };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, []);

  if (err) return <div style={{ padding: 24, color: "#f88" }}>Failed to load: {err}<br />Is the backend running on :8000?</div>;
  if (!data) return <div style={{ padding: 24, color: "#9aa" }}>Loading console…</div>;

  const m = metrics(data.exceptions, data.meta.runDate);
  const openException = openPk != null ? data.exceptions.find((e) => e.pk === openPk) || null : null;

  return (
    <div className="app">
      <div className="brand">
        <div className="logo">W</div>
        <div><div className="name">Wonder DQ Console</div><div className="sub">Inventory Data-Quality</div></div>
      </div>

      <header className="topbar">
        <span className="run-pill"><span className="dot" /> Validation run <b>{data.meta.runDate}</b> · processed <b>{data.meta.today}</b></span>
        <span className="run-pill">JIRA project <b>{data.meta.jiraProject}</b></span>
        <span className="spacer" />
        <span className="tip">Press <span className="kbd">1</span>–<span className="kbd">4</span> · <span className="kbd">/</span> search · <span className="kbd">Esc</span> close</span>
        <button className="btn sm" disabled={!!busy} onClick={() => runAction("run", "/run")}>{busy === "run" ? "Running…" : "↻ Run validation"}</button>
        <button className="btn sm" disabled={!!busy} onClick={() => runAction("sync", "/sync")}>{busy === "sync" ? "Syncing…" : "⟲ Sync from Jira"}</button>
        <span className="user"><span className="avatar">MD</span> Mike Dietrich · Accounting</span>
      </header>

      <nav className="sidebar" aria-label="Primary">
        <div className="nav-section">Workspace</div>
        <NavItem active={view === "dashboard"} onClick={() => setView("dashboard")} icon="▦" label="Reporting Dashboard" />
        <NavItem active={view === "workbench"} onClick={() => setView("workbench")} icon="▤" label="Exception Workbench" badge={m.open} />
        <NavItem active={view === "sla"} onClick={() => setView("sla")} icon="◷" label="Turnaround / SLA" />
        <NavItem active={view === "admin"} onClick={() => setView("admin")} icon="⚙" label="Rule & Routing Admin" />
        <div className="grow" />
        <div className="legend">
          Severity
          <div className="lg"><span className="sev-dot Urgent" /> Urgent · same day</div>
          <div className="lg"><span className="sev-dot High" /> High · 1d SLA</div>
          <div className="lg"><span className="sev-dot Medium" /> Medium · 2d SLA</div>
          <div className="lg"><span className="sev-dot Low" /> Low · 5d SLA</div>
        </div>
      </nav>

      <main className="main">
        {view === "dashboard" && <Dashboard data={data} drillTo={drillTo as any} />}
        {view === "workbench" && <Workbench data={data} drill={drill} clearDrill={() => setDrill(null)} onOpen={(e) => setOpenPk(e.pk)} refresh={load} />}
        {view === "sla" && <Sla data={data} drillTo={drillTo} ownerQueue={ownerQueue} openExc={openExc} />}
        {view === "admin" && <Admin data={data} />}
      </main>

      {openException && <Drawer data={data} exc={openException} onClose={() => setOpenPk(null)} refresh={load} />}
      <div className="proto-banner">PROTOTYPE · <b>React console</b> · live API + validation engine</div>
    </div>
  );
}

function NavItem({ active, onClick, icon, label, badge }: { active: boolean; onClick: () => void; icon: string; label: string; badge?: number }) {
  return <button className={"nav-item" + (active ? " active" : "")} onClick={onClick}><span className="nico">{icon}</span> {label}{badge != null && <span className="badge">{badge}</span>}</button>;
}
