# Prototypes — Wonder Inventory Data-Quality Console

These are **clickable, throwaway UI mockups** for stakeholder review. They are *not* the real application — there is no backend, no BigQuery, no JIRA. All data is fake sample data inlined in each folder.

## ✅ Approved direction — start here

The Jun 9 2026 walkthrough chose **Variant A (dense workbench) as the base, blended with Variant C's dashboard-led concept**. That blend is built out in:

| Folder | What it is |
|---|---|
| [`approved-console/`](approved-console/PrototypeD.html) | **The chosen direction.** Reporting Dashboard is the home screen (Variant C's KPIs + charts in Variant A's condensed style, darker-blue theme), Variant A's dense Exception Workbench kept as-is, a new *Errors by inventory movement type* breakout, dashboard drill-down, and the *ownership / sub-assignment* concept in the detail drawer (under review). Double-click `PrototypeD.html`. |

The three original variants below are **kept as reference** (they informed the blend); they are no longer the live target.

## How to open

Each folder is fully self-contained. Just **double-click the `*.html` file** inside it (`approved-console/PrototypeD.html`, or `PrototypeA/B/C.html` in the reference variants) — it opens in your browser with no server, no install, and works offline.

## The three reference directions

| Folder | Direction | Best for |
|---|---|---|
| [`variant-a-dense-workbench/`](variant-a-dense-workbench/PrototypeA.html) | **Dense Workbench** — information-dense data grid, heavy filtering/sorting, bulk actions, keyboard-friendly | Power users (data engineering, inventory ops) triaging many exceptions fast |
| [`variant-b-inbox/`](variant-b-inbox/PrototypeB.html) | **Inbox + Detail** — a clean, light, email-style 3-pane layout (folders → exception list → full detail panel), professional and approachable | Occasional & non-expert users across the company; familiar inbox metaphor |
| [`variant-c-dashboard-led/`](variant-c-dashboard-led/PrototypeC.html) | **Dashboard-Led** — metrics & charts first, click a tile/chart to drill into the underlying exceptions | Managers & accounting leadership wanting the big picture, then drill-down |

All three cover the **same four screens**: Exception list/triage, Reporting dashboard, Ticket turnaround / SLA, and Rule & routing admin — and all three demonstrate the flagship features (auto-created JIRA tickets, **auto-closed** tickets when data is fixed, recurring-error detection, SLA/turnaround tracking).

## How the direction was chosen

The three variants above were socialized with stakeholders. The winning blend — **Variant C's dashboard as the home page + Variant A's dense workbench** — is consolidated in [`approved-console/`](approved-console/PrototypeD.html); the production front-end (React) will be built from it. The reference variants are retained for traceability.

## Notes
- Sample run date shown is **2026-06-07** (prior day), as if validated on 2026-06-08.
- Fake data is internally consistent within each variant; numbers won't match across variants.
- Anything that looks editable (rule toggles, reassignments, notes) is mocked — changes don't persist.
