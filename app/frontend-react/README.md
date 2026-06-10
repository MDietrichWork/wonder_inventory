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

## Status (incremental rebuild)
- **Done:** app shell (brand, topbar with live Run/Sync, sidebar nav), **Reporting Dashboard**
  (KPIs, trend, system donut, by-type/facility/movement/severity bars, recurring leaderboard),
  **Exception Workbench** (filters, sort, drill-from-dashboard, search), and a **read-only detail
  drawer** (snapshot, ownership, timeline, the rule that fired, live over-receipt breakdown).
- **Next:** port Turnaround/SLA + Rule & Routing Admin screens; wire the drawer **write actions**
  (status change, reassign, hand-off, resolve) to the API; then Entra SSO + role-based views.

## Layout
- `src/types.ts` — the `/api/bootstrap` contract types
- `src/api.ts` — fetch + POST helpers
- `src/lib.ts` — aggregates / metrics / helpers (ports of the vanilla app's logic)
- `src/charts.tsx` — Trend, SystemDonut, HBars (SVG, same palette)
- `src/Dashboard.tsx`, `src/Workbench.tsx`, `src/Drawer.tsx`, `src/App.tsx`
