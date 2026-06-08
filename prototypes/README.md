# Prototypes — Wonder Inventory Data-Quality Console

These are **clickable, throwaway UI mockups** for stakeholder review. They are *not* the real application — there is no backend, no BigQuery, no JIRA. All data is fake sample data inlined in each folder. The goal is to **compare three UI directions and pick one** (or a blend) before any production code is written.

## How to open

Each variant is fully self-contained. Just **double-click the `Prototype*.html` file** inside any variant folder (`PrototypeA.html`, `PrototypeB.html`, `PrototypeC.html`) — it opens in your browser with no server, no install, and works offline.

## The three directions

| Folder | Direction | Best for |
|---|---|---|
| [`variant-a-dense-workbench/`](variant-a-dense-workbench/PrototypeA.html) | **Dense Workbench** — information-dense data grid, heavy filtering/sorting, bulk actions, keyboard-friendly | Power users (data engineering, inventory ops) triaging many exceptions fast |
| [`variant-b-inbox/`](variant-b-inbox/PrototypeB.html) | **Inbox + Detail** — a clean, light, email-style 3-pane layout (folders → exception list → full detail panel), professional and approachable | Occasional & non-expert users across the company; familiar inbox metaphor |
| [`variant-c-dashboard-led/`](variant-c-dashboard-led/PrototypeC.html) | **Dashboard-Led** — metrics & charts first, click a tile/chart to drill into the underlying exceptions | Managers & accounting leadership wanting the big picture, then drill-down |

All three cover the **same four screens**: Exception list/triage, Reporting dashboard, Ticket turnaround / SLA, and Rule & routing admin — and all three demonstrate the flagship features (auto-created JIRA tickets, **auto-closed** tickets when data is fixed, recurring-error detection, SLA/turnaround tracking).

## How to choose

Click through all three, ideally with the people who'll use it day-to-day. The directions are deliberately distinct so the contrast is obvious. Once a direction is chosen, **keep that folder and delete the other two** — the production front-end (React) will be built from the winner. A blend is fine too (e.g. "Variant C dashboard as the home page, Variant A workbench as the exception screen").

## Notes
- Sample run date shown is **2026-06-07** (prior day), as if validated on 2026-06-08.
- Fake data is internally consistent within each variant; numbers won't match across variants.
- Anything that looks editable (rule toggles, reassignments, notes) is mocked — changes don't persist.
