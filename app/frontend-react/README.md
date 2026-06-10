# Wonder DQ Console — React (Phase 5 rebuild)

The production rebuild of the approved console as a **Vite + React + TypeScript** app. It reuses the
approved `styles.css` verbatim, so the look matches the vanilla prototype, and talks to the **same**
FastAPI API (`/api/bootstrap`, `/run`, `/sync`, …). The vanilla console under `../frontend` stays in
place and is untouched.

## Run it locally
Node is installed standalone at `~/.local/bin/node` (no admin needed).

```bash
# 1) Start the backend (separate terminal), serving the API on :8000
cd ../backend && .venv/bin/uvicorn wonder.main:app --port 8000

# 2) Start the React dev server (hot-reload)
cd ../frontend-react
~/.local/bin/npm install      # first time only
~/.local/bin/npm run dev      # http://localhost:5173
```
Vite proxies `/api` → `http://127.0.0.1:8000`, so the React console runs against **live BigQuery +
Jira** data with hot-reload — edit a component or a validation rule (backend) and see it immediately.

## Status — full parity with the approved prototype
All four screens + the drawer are ported and verified headlessly (34-point feature QA, zero console errors):
- **Reporting Dashboard** — KPIs, trend, system donut, by-type/facility/movement/severity bars,
  recurring leaderboard, all with dashboard→workbench drill-down.
- **Exception Workbench** — search + 8 filters, sortable 14-col grid, drill chip, row selection +
  **bulk bar** (reassign / comment / mark-resolved / clear).
- **Detail drawer** — snapshot, live over-receipt breakdown table (+ UoM/duplicate warnings),
  ownership & hand-off, colored JIRA/ownership **timeline**, **Notes**, and the action footer
  (**status select**, Open-in-JIRA, **Reassign owner**, **Hand off…**, Add note) wired to the API.
- **Turnaround / SLA** — aging buckets, by-team, by-owner (click → accountability queue), by-holder
  (held-time), overdue table.
- **Rule & Routing Admin** — rules table + enable toggles, rule editor, routing map, SLA targets.
- **Keyboard:** `1`–`4` switch screens, `/` focus search, `Esc` close drawer.

Notes are local-mock (matching the prototype); wiring them to real Jira comments is a small backend add.
- **Next:** Entra SSO + role-based views; then at deploy, build `dist` and have the container serve it.

## Layout
- `src/types.ts` — the `/api/bootstrap` contract types
- `src/api.ts` — fetch + POST helpers
- `src/lib.ts` — aggregates / metrics / helpers (ports of the vanilla app's logic)
- `src/charts.tsx` — Trend, SystemDonut, HBars (SVG, same palette)
- `src/Dashboard.tsx`, `src/Workbench.tsx`, `src/Drawer.tsx`, `src/App.tsx`
