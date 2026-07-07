# Validation Rule SQL — Plain-English Guide

> A companion to [`validation-tests.md`](validation-tests.md). That file lists *what* each rule
> checks; **this file explains the *SQL* behind each rule** — line by line, in plain English, so a
> non-technical reader can understand exactly what the query does, which tables and columns it
> touches, and why it is written the way it is.

---

## How to read this guide

Each rule is documented with the same six parts:

1. **Header** — the rule number and the friendly error-type name you see in the Exceptions
   Workbench.
2. **At a glance** — severity, SLA, who owns it, and where its tickets are filed.
3. **The SQL** — shown in up to two versions, side by side:
   - **Catalog SQL** — the clean, documented version shown in the Admin → Rule editor. It is the
     reference definition of the rule.
   - **Live finder SQL** — the query that actually runs each day inside `bq_finder.py` and creates
     the exceptions you see in the app. For some rules this is identical to the catalog version;
     for others it differs (and we explain why). A few catalog rules are **not wired into the live
     finder yet** — those are clearly marked.
4. **Plain-English walkthrough** — the query explained one piece at a time, no SQL knowledge assumed.
5. **Tables & columns used** — every table and key column the query touches, what each column means
   in business terms, and — where the query joins two tables — which columns join and *why*.
6. **Example of a flagged record** — a concrete (anonymized) example of a row this rule would catch.

**A note on tables.** All inventory rules read from the data warehouse
`wonder-dw-prod-brd.inventory`. The two tables you'll see most often:

| Friendly name | Real table | What it is |
|---|---|---|
| **The Inventory Ledger** | `consolidated_inventory_ledger` | One row per inventory *movement* — every receipt, transfer, adjustment, waste, correction, etc. This is the system's running diary of what happened to inventory. |
| **The PO Table** | `int_ledger_purchase_orders` | One row per purchase-order line — what we *ordered* from a supplier, how much, at what price, and how much has been received. |

**Severity & SLA** (full definitions in [`validation-tests.md`](validation-tests.md)):

| Severity | SLA (business days) |
|---|---|
| **Urgent** | 0 — same day |
| **High** | 1 day |
| **Medium** | 2 days |
| **Low** | 3–5 days |

---

## PO-01 · Inventory Log Missing PO Number

> **In one sentence:** find any receiving record from yesterday that says it came in against a
> purchase order but has no purchase-order number filled in — so we can't tell which order it
> belongs to.

### At a glance

| | |
|---|---|
| **Rule number** | PO-01 |
| **Rule type** | `NOT_NULL` (a "this field must not be blank" check) |
| **Severity** | **Urgent** — same-day SLA |
| **Owner / routed team** | SC Product (IMS) |
| **Default assignee** | Sarah Chen |
| **Jira** | Project **WIQ** · Component **Ledger Ingest** |
| **Source table** | The Inventory Ledger (`consolidated_inventory_ledger`) |
| **Live status** | ✅ **Live — runs in the daily validation job.** It is switched on as a safety-net. On today's data it finds **0 rows** (every PO receipt already carries a PO number), so it creates no tickets right now — but it will the moment a blank-PO receipt appears. |

### The SQL

The two versions below do **the same check** — they differ only in plumbing. The catalog version is
the plain-English-friendly statement of the rule; the live version is what the daily job actually
runs and is what you see in the Admin → Rule editor.

#### Catalog SQL (the documented definition)

```sql
-- A PO-order-type receiving row that carries no PO id (ref_order_id NULL/blank).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
SELECT id, datetime_utc, facility_name, system_of_origin, l1_action, l2_action,
       consumable_sku, item_name, ref_order_type, ref_order_id
FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
WHERE ref_order_type = 'Purchase Order'
  AND (ref_order_id IS NULL OR TRIM(ref_order_id) = '')
  AND DATE(datetime_utc) = run_date
ORDER BY datetime_utc DESC
```

#### Live finder SQL (what runs daily)

```sql
-- A PO-order-type receiving row in the ledger with a NULL/blank PO number (safety-net).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH flagged AS (
  SELECT CAST(id AS STRING) AS id, ANY_VALUE(facility_name) AS facility,
         ANY_VALUE(system_of_origin) AS system, ANY_VALUE(consumable_sku) AS consumable_sku,
         ANY_VALUE(item_name) AS item_name, ANY_VALUE(l1_action) AS l1_action,
         ANY_VALUE(l2_action) AS l2_action, MIN(datetime_utc) AS datetime_utc
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Purchase Order'
    AND (ref_order_id IS NULL OR TRIM(ref_order_id) = '')
    AND DATE(datetime_utc) = run_date
  GROUP BY id),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY datetime_utc DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 500 ORDER BY datetime_utc DESC
```

### Plain-English walkthrough

Both SQL blocks above run the **same check** — the catalog version is the short, readable statement
of the rule, and the live version adds the production "plumbing" the daily job needs. The
walkthrough below explains the **live version**, since that's what actually runs; it covers
everything in the catalog version along the way.

**First, how the query is shaped.** SQL lets you build a result in named *steps* using the form
`WITH <name> AS ( … )`. Think of each step as a labeled scratch list that the next step can reuse.
This query has two steps — one named **`flagged`** and one named **`ranked`** — followed by a final
line that picks the rows to keep. Reading it as *"build a list called `flagged`, then a list called
`ranked`, then choose from `ranked`"* is exactly right. (`AS` just means "name this step.")

**The run date.** `DECLARE run_date … = yesterday` defines the day we're checking. `CURRENT_DATE()`
is today and `DATE_SUB(…, INTERVAL 1 DAY)` subtracts a day, so **`run_date` = yesterday**. The daily
job always checks the previous, fully-closed day, because today's data is still arriving.

**Step 1 — `flagged`: find the problem rows.** This step builds the list of offending receipts.
- `FROM … consolidated_inventory_ledger` — look in the **Inventory Ledger** (one row per inventory movement).
- `WHERE ref_order_type = 'Purchase Order'` — keep only **purchase-order receipts** (inventory arriving because we bought it).
- `AND (ref_order_id IS NULL OR TRIM(ref_order_id) = '')` — **the heart of the rule**: of those, keep only the ones whose **PO number is missing** — either truly empty (`IS NULL`) or only blank spaces (`TRIM(…) = ''`, where `TRIM` strips spaces so `"   "` counts as empty).
- `AND DATE(datetime_utc) = run_date` — and only ones that happened **yesterday**.
- `GROUP BY id` — collapse the result to **one row per ledger record** (`id` is each record's unique number), so a bad receipt is listed once, not repeatedly.
- `SELECT CAST(id AS STRING) AS id, ANY_VALUE(facility_name) AS facility, …` — for each bad record, grab the details a person needs to fix it: the facility, source system, item, the kind of movement, and when it happened. Two bits of housekeeping: `CAST(id AS STRING)` just means "treat the id as text," and `ANY_VALUE(…)` means "since we've grouped to one row, give me that row's value for this column."

So after Step 1, **`flagged`** is a clean, de-duplicated list of yesterday's blank-PO receipts.

**Step 2 — `ranked`: number them, newest first.** This step takes the `flagged` list and adds two
helper columns:
- `COUNT(*) OVER() AS total_matches` — count **all** the matches and stamp that total onto every row, so the app can say *"showing 500 of 1,200"* even when it only displays some.
- `ROW_NUMBER() OVER (ORDER BY datetime_utc DESC) AS rn` — sort the rows newest-first and number them 1, 2, 3, … in a column called `rn` ("row number"). Row 1 is the most recent.

**Final line — keep the newest 500.** `SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 500 ORDER BY
datetime_utc DESC` does three things: keep only rows numbered **500 or lower** — a **safety cap** so
one bad-data day can never create more than 500 tickets and flood the queue; drop the helper `rn`
column from the output (`EXCEPT(rn)` means "every column except this one"); and present what's left
**newest-first**. On a normal day there are far fewer than 500 matches — today there are **0**.

### Tables & columns used

**Table:** The Inventory Ledger — `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`

| Column | Plain meaning | Role in this rule |
|---|---|---|
| `ref_order_type` | What kind of order the movement relates to (e.g. *Purchase Order*, *Transfer Order*). | **Filter** — keep only `Purchase Order` rows. |
| `ref_order_id` | The purchase-order number the receipt belongs to. | **The check** — flag when this is null or blank. |
| `datetime_utc` | Exact UTC timestamp of the movement. | **Filter** — keep only yesterday; also sort newest-first. |
| `id` | Unique id for the Inventory Ledger row. | Identifies the exact record to fix; used as the ticket fingerprint. |
| `facility_name` | Which facility recorded the movement. | Triage — tells the owner *where* it happened. |
| `system_of_origin` | The upstream system the record came from (Pantry / Ship Hero / Fishbowl). | Triage — points to where the data was entered. |
| `l1_action` / `l2_action` | The movement's action category and sub-action (e.g. *Add* / *Receipt*). | Context — what kind of movement this was. |
| `consumable_sku` | The item identifier (SKU) involved. | Triage — *what* item came in. |
| `item_name` | Human-readable item name. | Triage — the item in plain words. |

### Example of a flagged record (illustrative)

> PO-01 is live but finds **0 rows on today's data** (every PO receipt is currently numbered), so
> there are no real exceptions to show yet. The row below is a **hand-built illustration** of what a
> catch will look like the first time a blank-PO receipt lands — not an actual record from the
> warehouse.

A receipt that arrived yesterday, was tagged as a Purchase Order receipt, but came in with the PO
number blank:

| Column | Value |
|---|---|
| `id` | `led_8f3a91c4` |
| `datetime_utc` | `2026-06-28 14:22:07 UTC` |
| `facility_name` | `Dallas – Lone Star Kitchen` |
| `system_of_origin` | `Ship Hero` |
| `l1_action` / `l2_action` | `Add` / `Receipt` |
| `consumable_sku` | `CSK-104882` |
| `item_name` | `Shredded Mozzarella, 5 lb` |
| `ref_order_type` | `Purchase Order` |
| `ref_order_id` | *(blank)* ← **the problem** |

**Why it's flagged:** it claims to be a purchase-order receipt, but with no PO number we can't match
it to what was ordered, can't validate quantity or price, and can't close out the PO — hence the
**Urgent** severity and same-day SLA.

---

## PO-03 · PO Over Receipt

> **In one sentence:** find purchase orders that received stock yesterday where the **total received
> has gone over what was ordered** — or where the receipt came in on a different unit of measure than
> the order.

### At a glance

| | |
|---|---|
| **Rule number** | PO-03 |
| **Rule type** | `RANGE` (a "the value must stay within an expected range" check — here, received vs ordered) |
| **Severity** | **Banded by how far over:** 30–99% over → **High** (a supply-chain signal, e.g. an over-shipment); ≥100% over (received ≥ 2× ordered) → **Urgent** (a likely receiving error like a double-scan). A unit-of-measure mismatch is split off as its own error type (`PO_UOM_MISMATCH`). |
| **Owner / routed team** | Field Ops |
| **Default assignee** | Diego Alvarez |
| **Jira** | Project **WIQ** · Component **Receiving** |
| **Source tables** | Inventory Ledger **⋈** PO Table (joined) |
| **Live status** | 🟢 **Live — runs daily.** Flagged **0** on yesterday's data (no over-receipts booked yesterday); it fires whenever a PO's cumulative receipts cross the over-receipt threshold. |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- DAILY BATCH PO over-receipt: flag POs that RECEIVED yesterday, then compare their
-- cumulative received-to-date vs ordered.
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday
WITH touched AS (   -- (po, item) received on run_date
  SELECT DISTINCT ref_order_id AS po, consumable_sku
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type='Purchase Order' AND consumable_sku IS NOT NULL AND DATE(datetime_utc)=run_date),
received AS (       -- cumulative received-to-date for those POs (30-day lookback)
  SELECT l.ref_order_id AS po, l.consumable_sku, SUM(l.consumable_quantity_change) AS received_qty,
         ANY_VALUE(l.consumable_uom) AS received_uom
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` l
  JOIN touched t ON l.ref_order_id=t.po AND l.consumable_sku=t.consumable_sku
  WHERE l.ref_order_type='Purchase Order' AND DATE(l.datetime_utc)<=run_date
    AND l.datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(run_date), INTERVAL 30 DAY)
  GROUP BY po, consumable_sku),
ordered AS (
  SELECT po, consumable_sku, SUM(consumable_sku_qty) AS ordered_qty, ANY_VALUE(consumable_uom) AS ordered_uom
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE consumable_sku IS NOT NULL AND order_type = 'Purchase'
  GROUP BY po, consumable_sku)
SELECT r.po, r.consumable_sku, o.ordered_qty, r.received_qty,
       (o.ordered_uom != r.received_uom) AS uom_mismatch,
       ROUND((SAFE_DIVIDE(r.received_qty,o.ordered_qty)-1)*100,1) AS over_by_pct
FROM received r JOIN ordered o USING (po, consumable_sku)
WHERE o.ordered_qty>0 AND ( (o.ordered_uom != r.received_uom) OR r.received_qty > o.ordered_qty*1.05 )
ORDER BY over_by_pct DESC
```

#### Live finder SQL (what runs daily)

```sql
-- PO over-receipt + UoM mismatch (daily: POs that received on run_date, cumulative vs ordered).
-- uom_mismatch=TRUE rows become PO_UOM_MISMATCH; the rest PO_OVER_RECEIPT (>=100% over -> Urgent).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH evt AS (   -- every ledger line for a PO+item touched yesterday, with a RUNNING cumulative received
  SELECT l.ref_order_id AS po, l.consumable_sku, l.datetime_utc,
         l.consumable_quantity_change AS q, l.consumable_uom AS ruom,
         l.facility_name AS facility, l.facility_type AS facility_type,
         l.system_of_origin AS system, l.item_name AS item_name, l.l1_action, l.l2_action,
         SUM(l.consumable_quantity_change) OVER (
           PARTITION BY l.ref_order_id, l.consumable_sku ORDER BY l.datetime_utc
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_recv
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` l
  JOIN (SELECT DISTINCT ref_order_id AS po, consumable_sku
        FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
        WHERE ref_order_type='Purchase Order' AND consumable_sku IS NOT NULL
          AND DATE(datetime_utc)=run_date) t
    ON l.ref_order_id=t.po AND l.consumable_sku=t.consumable_sku
  -- NOTE: capturing EVERY Purchase-Order line (positive AND negative) makes SUM(q) a true NET, so a
  -- correction booked back against the PO cancels the bad receipt. (See walkthrough.)
  WHERE l.ref_order_type='Purchase Order' AND l.consumable_sku IS NOT NULL
    AND DATE(l.datetime_utc)<=run_date
    AND l.datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(run_date), INTERVAL 30 DAY)),
received AS (   -- net received per PO+item
  SELECT po, consumable_sku, SUM(q) AS received_qty, ANY_VALUE(ruom) AS received_uom,
         ANY_VALUE(facility) AS facility, ANY_VALUE(facility_type) AS facility_type,
         ANY_VALUE(system) AS system, ANY_VALUE(item_name) AS item_name,
         ANY_VALUE(l1_action HAVING MAX q) AS move_l1, ANY_VALUE(l2_action HAVING MAX q) AS move_l2
  FROM evt GROUP BY po, consumable_sku),
ordered AS (   -- ordered qty + unit per PO+item, from the PO table
  SELECT po, consumable_sku, SUM(consumable_sku_qty) AS ordered_qty,
         ANY_VALUE(consumable_uom) AS ordered_uom, ANY_VALUE(supplier_name) AS supplier, ANY_VALUE(status) AS status
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE consumable_sku IS NOT NULL AND order_type='Purchase'
  GROUP BY po, consumable_sku),
breach AS (   -- the date each problem first started (when cumulative first crossed the line)
  SELECT e.po, e.consumable_sku,
         DATE(MIN(IF(e.running_recv > o.ordered_qty*(1+0.3), e.datetime_utc, NULL))) AS over_breach_date,
         DATE(MIN(IF(o.ordered_uom IS NOT NULL AND e.ruom IS NOT NULL AND e.ruom!=o.ordered_uom,
                     e.datetime_utc, NULL))) AS uom_breach_date,
         DATE(MIN(e.datetime_utc)) AS first_receipt_date, DATE(MAX(e.datetime_utc)) AS last_receipt_date
  FROM evt e JOIN ordered o USING (po, consumable_sku) GROUP BY po, consumable_sku),
flagged AS (   -- keep only PO+items that are over by >30% OR have a UoM mismatch
  SELECT r.po, r.consumable_sku, r.item_name, o.ordered_qty, r.received_qty, o.ordered_uom, r.received_uom,
         r.facility, r.facility_type, r.system, o.supplier, o.status, r.move_l1, r.move_l2,
         SAFE_DIVIDE(r.received_qty, o.ordered_qty) - 1 AS over_frac,
         (o.ordered_uom IS NOT NULL AND r.received_uom IS NOT NULL AND o.ordered_uom!=r.received_uom) AS uom_mismatch,
         b.over_breach_date, b.uom_breach_date, b.first_receipt_date, b.last_receipt_date
  FROM received r JOIN ordered o USING (po, consumable_sku) JOIN breach b USING (po, consumable_sku)
  WHERE o.ordered_qty>0 AND ( (o.ordered_uom!=r.received_uom) OR r.received_qty > o.ordered_qty*(1+0.3) )),
ranked AS (   -- number rows within each severity band so the 500 cap keeps all bands represented
  SELECT *, COUNT(*) OVER() AS total_matches,
         ROW_NUMBER() OVER (
           PARTITION BY (CASE WHEN uom_mismatch THEN 'uom'
                              WHEN over_frac >= 1.0 THEN 'over_urgent' ELSE 'over_high' END)
           ORDER BY over_frac DESC) AS rn
  FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 500 ORDER BY over_frac DESC
```

### Plain-English walkthrough

This is the most involved rule, because "did we receive too much?" means comparing two different
things — what the ledger says we **received** against what the PO table says we **ordered** — and
adding it up over time. The live query builds the answer in named steps (`WITH <name> AS ( … )`);
read it as a short pipeline. Both SQL blocks do the same job; the catalog version is the simpler
documented form, and the **live version's thresholds are the ones actually in force** (30% / 100%).

1. **`run_date` = yesterday** — the day we're checking.

2. **`evt` — pull the receipt history for the POs that moved yesterday.** First it finds every
   (PO, item) that *received something yesterday* (the small `JOIN (… DATE(datetime_utc)=run_date …)`
   sub-query) — we only re-examine POs that actually had activity, which keeps the query cheap. For
   each of those, it pulls **every** ledger line tied to that PO over the last **30 days** and adds a
   **running cumulative total** (`running_recv`) — a column that, row by row in time order, says "how
   much have we received against this PO+item *so far*." Why include positive **and** negative lines?
   Because if a receiver over-logs a receipt and a correction is later booked back against the same
   PO, the two cancel out — so the running total is a **true net**, and we don't flag a mistake that
   was already fixed.

3. **`received` — the bottom line per PO+item.** Collapses `evt` to one row per (PO, item) with the
   **net received quantity** and its unit of measure, plus details for triage (facility, system, the
   dominant receiving action).

4. **`ordered` — what the PO actually called for.** From the **PO Table**, the **ordered quantity**
   and unit per (PO, item), plus supplier and PO status.

5. **`breach` — when the problem started.** For each (PO, item) it finds the **first** receipt at
   which the running total crossed the over-receipt line, and the first receipt that introduced a
   wrong unit. This gives the exception an accurate "as of" date instead of just "today."

6. **`flagged` — apply the test.** Joins received ↔ ordered ↔ breach and keeps a row only if
   **received is more than 30% over ordered**, *or* the **received unit doesn't match the ordered
   unit**. It also computes `over_frac` = received ÷ ordered − 1 (e.g. 0.5 = 50% over), which decides
   the severity band.

7. **`ranked` + final line — fair capping.** Rows are numbered *within each band* (UoM mismatch /
   30–99% over / ≥100% over) so the **500-row daily cap** keeps all three populations represented
   rather than letting the most extreme rows crowd out the rest. The final line drops the helper
   number and sorts worst-first.

**How the join works & why it's needed:** the ledger and the PO table are stitched together on
**`ledger.ref_order_id = PO.po`** (same purchase order) **and** **`consumable_sku = consumable_sku`**
(same item) — see the `USING (po, consumable_sku)` joins. Without the join we'd only know what we
*received*; we need the PO table to know what was *ordered* so we can compare the two.

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** PO Table (`int_ledger_purchase_orders`).
**Join keys:** `ref_order_id` ⇄ `po` (the purchase order) and `consumable_sku` ⇄ `consumable_sku` (the item).

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `ref_order_id` (ledger) | The PO a receipt belongs to. | **Join key** to the PO table; identifies the order. |
| `consumable_quantity_change` (ledger) | How much the item moved on that line (+ in, − out). | **Summed** into the net received quantity. |
| `consumable_uom` (ledger) | The unit the receipt was booked in. | Compared to the ordered unit (UoM-mismatch check). |
| `datetime_utc` (ledger) | When the movement happened. | Picks "touched yesterday", the 30-day window, and the breach date. |
| `consumable_sku_qty` (PO) | The quantity ordered on the PO line. | **The benchmark** — received is compared against this. |
| `consumable_uom` (PO) | The unit the item was ordered in. | Compared to the received unit. |
| `supplier_name`, `status` (PO) | Vendor and PO status. | Triage context on the ticket. |
| `facility_name` / `facility_type` (ledger) | Where it was received. | Triage + routing (HDR vs CK/Production). |

### Example of a flagged record (from the dashboard)

A live exception currently open in the Workbench — **ERR-00006** (Jira **KAN-855**), routed to
Field Ops — ProdCo:

| Field | Value |
|---|---|
| `po` | `88 ARCADIA FIX 060226` |
| `consumable_sku` / `item_name` | `5182551` / `Crust, Square, DiFara (Co-Man V3)` |
| `ordered_qty` (PO) | `12 ea` |
| `received_qty` (ledger, net) | `240 ea` |
| `over_by_pct` | `1,900%` over → **Urgent** |
| `supplier` / `facility` (type) | `RM Bakery LLC (Leaven Co)` / `DISH` (DISH) |
| `breached_at` | `2026-06-02` |

**Why it's flagged:** 240 received against an order of 12 is **20× the quantity ordered** — far past
the ≥100% line, so it lands in the **Urgent** band (a likely double-receive / receiving error, not
just an over-shipment).

---

## PO-07 · PO Overdue — No Receipt

> **In one sentence:** find **open** purchase orders that are **past their expected delivery date**
> with **nothing received** against them and **not cancelled** — the order is in limbo and needs to be
> chased or cancelled.

### At a glance

| | |
|---|---|
| **Rule number** | PO-07 |
| **Rule type** | `AGING` (a "this should have happened by now" timeliness check) |
| **Severity** | **Medium** — 2-day SLA |
| **Owner / routed team** | Procurement |
| **Default assignee** | Tom Becker |
| **Jira** | Project **WIQ** · Component **PO Fulfillment** |
| **Source table** | PO Table (`int_ledger_purchase_orders`) |
| **Grain** | **One ticket per PO** (not per line). |
| **Key settings** | `po_no_receipt_overdue_days` = **2** (grace days past expected) · `po_no_receipt_overdue_lookback_days` = **7** (only recently-overdue POs; 0 = full backlog) |
| **Live status** | 🟢 **Live — runs daily.** With the 7-day window it flagged **2** POs on the 2026-07-06 run (`KAN-1041`, `KAN-1042`). |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Framework PO-07: an OPEN Purchase PO past expected_date + N days with nothing received and
-- not cancelled. Aggregated to PO grain — a PO is 'nothing received' only when NO line has any
-- received_qty. N = po_no_receipt_overdue_days (default 2).
SELECT po, ANY_VALUE(destination_name) AS facility, ANY_VALUE(supplier_name) AS supplier_name,
       MAX(expected_date) AS expected_date, SUM(COALESCE(received_qty,0)) AS total_received
FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
WHERE order_type = 'Purchase' AND UPPER(status) = 'OPEN'
GROUP BY po
HAVING total_received = 0 AND MAX(expected_date) < DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
```

#### Live finder SQL (what runs daily)

```sql
-- Open Purchase PO past expected_date + 2 days with nothing received and not cancelled
-- (framework PO-07), limited to the last 7 days. One row per PO.
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH po_agg AS (
  SELECT po,
         ANY_VALUE(destination_name) AS facility,
         ANY_VALUE(supplier_name)    AS supplier_name,
         ANY_VALUE(po_source_system) AS system,
         SUM(COALESCE(received_qty, 0)) AS total_received,          -- across ALL lines of the PO
         LOGICAL_OR(UPPER(status) = 'OPEN') AS has_open_line,       -- still awaiting receipt somewhere
         STRING_AGG(DISTINCT status, ', ') AS po_status,
         COUNT(*) AS line_count,
         MAX(IF(UPPER(status) = 'OPEN', expected_date, NULL)) AS expected_date,
         SUM(IF(UPPER(status) = 'OPEN', COALESCE(consumable_sku_qty, 0), 0)) AS total_ordered,
         COUNTIF(UPPER(status) = 'OPEN') AS open_line_count
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase' AND po IS NOT NULL AND TRIM(po) <> ''
  GROUP BY po),
flagged AS (
  SELECT *,
         DATE_ADD(expected_date, INTERVAL 2 DAY) AS breach_date,
         DATE_DIFF(run_date, expected_date, DAY) AS days_overdue
  FROM po_agg
  WHERE total_received = 0              -- nothing received on the whole PO
    AND has_open_line                  -- still open / not cancelled or closed out
    AND expected_date IS NOT NULL
    AND expected_date < DATE_SUB(run_date, INTERVAL 2 DAY)
    AND expected_date >= DATE_SUB(run_date, INTERVAL 7 DAY)),   -- recency window
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY expected_date ASC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 500 ORDER BY expected_date ASC
```

### Plain-English walkthrough

This rule reads a single table (the **PO Table**) and rolls every PO line up to **one row per PO**,
so the whole order is judged together — not each line separately.

1. **`run_date` = yesterday.**

2. **`po_agg` — summarise each PO.** Group all of a PO's lines and compute:
   - `total_received` = the sum of received quantity across **every** line. A PO only counts as
     "nothing received" when this is exactly **0** — so a partially-received order is *not* caught here
     (that's PO-08).
   - `has_open_line` = is any line still **Open**? If yes, the order is still awaiting receipt and
     hasn't been cancelled or closed.
   - `expected_date` = the latest expected date **among the still-open lines** — the schedule for the
     part that hasn't arrived.

3. **`flagged` — keep the stuck POs.** Keep a PO only when **all** are true:
   - `total_received = 0` — nothing received at all.
   - `has_open_line` — still open (so, by definition, **not cancelled and not closed**).
   - `expected_date < run_date − 2 days` — more than the 2-day grace past due.
   - `expected_date >= run_date − 7 days` — the **recency window**: only POs that came due in the last
     week, so the first rollout is a small, current batch instead of years of backlog. Set the
     `..._lookback_days` setting to 0 to switch this off and sweep the full backlog (e.g. at go-live).
   - `breach_date` (expected + 2 days) is stamped on the ticket as the age/SLA anchor; `days_overdue`
     is shown for triage.

4. **`ranked` + final line — cap.** Stamp the total match count on every row, order oldest-expected
   first (most overdue surface first), keep the first 500, drop the helper column.

**Auto-close:** each day the rule re-checks every open PO-07 ticket and closes it once the PO has a
receipt, or Supply Chain cancels/closes it.

### Tables & columns used

**Table:** PO Table — `int_ledger_purchase_orders`. **Joins:** none (single-table, grouped by PO).

| Column | Plain meaning | Role in this rule |
|---|---|---|
| `received_qty` | How much has been received on the line. | **The check** — summed per PO; must be 0. |
| `status` | The PO line's lifecycle status. | **The check** — at least one line must be `Open`. |
| `expected_date` | When the line was due to be received. | **The check** — must be >2 days (and ≤7 days) before yesterday. |
| `order_type` | Purchase vs Transfer. | **Filter** — purchases only. |
| `consumable_sku_qty` | Ordered quantity (consumable units). | Context (ordered qty) shown on the ticket. |
| `po`, `destination_name`, `supplier_name` | PO number, facility, vendor. | Triage context on the ticket. |

### Example of a flagged record (from the dashboard)

A live exception opened by the 2026-07-06 run — **Jira KAN-1041**, routed to Procurement:

| Field | Value |
|---|---|
| `po` | `FB-8991` |
| `supplier_name` | `Baldor Specialty Foods` |
| `facility` | `CK1` |
| `po_status` | `Open` ← still open, not cancelled |
| `expected_date` | `2026-06-29` |
| `days_overdue` | `7` ← **the problem** |
| `received_qty` | `0` |

**Why it's flagged:** the PO was due 2026-06-29, nothing has been received, and it's still Open (not
cancelled) 7 days later — Procurement needs to chase the delivery or cancel the order.

---

## PO-08 · PO Partially Received — Not Closed

> **In one sentence:** find purchase orders that received **some but not all** of what was ordered
> (short by even 1) and are **past their expected date without being closed** — the outstanding balance
> is stuck in limbo.

### At a glance

| | |
|---|---|
| **Rule number** | PO-08 |
| **Rule type** | `AGING` (a "this should have happened by now" timeliness check) |
| **Severity** | **Medium** — 2-day SLA |
| **Owner / routed team** | Procurement |
| **Default assignee** | Tom Becker |
| **Jira** | Project **WIQ** · Component **PO Fulfillment** |
| **Source table** | PO Table (`int_ledger_purchase_orders`) |
| **Grain** | **One ticket per PO** (not per line). |
| **Key settings** | `po_partial_not_closed_days` = **3** (grace days past expected) · `po_partial_not_closed_lookback_days` = **7** (only recently-overdue POs; 0 = full backlog) |
| **Live status** | 🟢 **Live — runs daily.** With the 7-day window it flagged **1** PO on the 2026-07-06 run (`KAN-1043`). |

> **A note on units.** Ordered vs received is compared in **supplier units**: `received_qty` tracks the
> `supplier_sku_qty` column (the quantity ordered from the vendor), not the consumable quantity.

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Framework PO-08: a Purchase PO under-received (received > 0 but < ordered) that is still not
-- closed Y days past expected_date. PO grain; ordered compared in supplier units.
-- N = po_partial_not_closed_days (default 3).
SELECT po, ANY_VALUE(destination_name) AS facility, ANY_VALUE(supplier_name) AS supplier_name,
       MAX(expected_date) AS expected_date, SUM(COALESCE(received_qty,0)) AS total_received,
       SUM(COALESCE(supplier_sku_qty,0)) AS total_ordered
FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
WHERE order_type = 'Purchase'
  AND UPPER(status) NOT IN ('CLOSED','COMPLETED','CANCELLED','CANCELED','VOIDED')
GROUP BY po
HAVING total_received > 0 AND total_received < total_ordered
   AND MAX(expected_date) < DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
```

#### Live finder SQL (what runs daily)

```sql
-- Under-received Purchase PO (received>0 but < ordered) still not closed 3 days past
-- expected_date (framework PO-08), limited to the last 7 days. One row per PO.
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH po_agg AS (
  SELECT po,
         ANY_VALUE(destination_name) AS facility,
         ANY_VALUE(supplier_name)    AS supplier_name,
         ANY_VALUE(po_source_system) AS system,
         SUM(COALESCE(received_qty, 0))     AS total_received,   -- supplier units, across ALL lines
         SUM(COALESCE(supplier_sku_qty, 0)) AS total_ordered,   -- supplier units, across ALL lines
         LOGICAL_OR(UPPER(status) NOT IN ('CLOSED','COMPLETED','CANCELLED','CANCELED','VOIDED')) AS not_closed,
         STRING_AGG(DISTINCT status, ', ') AS po_status,
         COUNT(*) AS line_count,
         MAX(IF(UPPER(status) NOT IN ('CLOSED','COMPLETED','CANCELLED','CANCELED','VOIDED'), expected_date, NULL)) AS expected_date,
         COUNTIF(UPPER(status) NOT IN ('CLOSED','COMPLETED','CANCELLED','CANCELED','VOIDED')) AS open_line_count
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase' AND po IS NOT NULL AND TRIM(po) <> ''
  GROUP BY po),
flagged AS (
  SELECT *,
         total_ordered - total_received AS shortfall_qty,
         DATE_ADD(expected_date, INTERVAL 3 DAY) AS breach_date,
         DATE_DIFF(run_date, expected_date, DAY) AS days_overdue
  FROM po_agg
  WHERE total_received > 0                       -- received something
    AND total_received < total_ordered - 0.001   -- but under-received (short by even 1)
    AND not_closed                               -- not closed by Supply Chain
    AND expected_date IS NOT NULL
    AND expected_date < DATE_SUB(run_date, INTERVAL 3 DAY)
    AND expected_date >= DATE_SUB(run_date, INTERVAL 7 DAY)),   -- recency window
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY expected_date ASC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 500 ORDER BY expected_date ASC
```

### Plain-English walkthrough

Like PO-07, this reads only the **PO Table** and rolls each PO up to **one row**, judging the whole
order together. The difference is *what* it looks for: a **partial** receipt that never got closed.

1. **`run_date` = yesterday.**

2. **`po_agg` — summarise each PO.** For every PO, sum `received_qty` and `supplier_sku_qty` across all
   its lines (both in supplier units), record whether it's `not_closed` (any line still in a
   non-terminal status), and take the expected date of the not-yet-closed lines.

3. **`flagged` — keep the stuck partials.** Keep a PO only when **all** are true:
   - `total_received > 0` — **something** was received (this is what separates it from PO-07).
   - `total_received < total_ordered − 0.001` — but it's **short of what was ordered** (by even 1; the
     tiny `0.001` just absorbs floating-point noise).
   - `not_closed` — Supply Chain hasn't closed or cancelled it, so the shortfall is still outstanding.
   - `expected_date < run_date − 3 days` — more than the 3-day grace past due.
   - `expected_date >= run_date − 7 days` — the same **recency window** as PO-07 (set the lookback
     setting to 0 to sweep the full backlog).
   - `shortfall_qty` (ordered − received) and `days_overdue` are stamped on the ticket for triage;
     `breach_date` (expected + 3 days) is the age/SLA anchor.

4. **`ranked` + final line — cap.** Same as the other rules: count, order oldest-expected first, keep
   the first 500.

**Auto-close:** each day the rule re-checks every open PO-08 ticket and closes it once the PO is fully
received (received ≥ ordered) or Supply Chain closes/cancels it.

### Tables & columns used

**Table:** PO Table — `int_ledger_purchase_orders`. **Joins:** none (single-table, grouped by PO).

| Column | Plain meaning | Role in this rule |
|---|---|---|
| `received_qty` | How much has been received (supplier units). | **The check** — summed per PO; must be > 0 but < ordered. |
| `supplier_sku_qty` | How much was ordered from the vendor (supplier units). | **The check** — the ordered total to compare against. |
| `status` | The PO line's lifecycle status. | **The check** — at least one line must be non-terminal (not closed/cancelled). |
| `expected_date` | When the line was due to be received. | **The check** — must be >3 days (and ≤7 days) before yesterday. |
| `order_type` | Purchase vs Transfer. | **Filter** — purchases only. |
| `po`, `destination_name`, `supplier_name` | PO number, facility, vendor. | Triage context on the ticket. |

### Example of a flagged record (from the dashboard)

A live exception opened by the 2026-07-06 run — **Jira KAN-1043**, routed to Procurement:

| Field | Value |
|---|---|
| `po` | `s-20260629-1` |
| `supplier_name` | `Ed Don` |
| `po_status` | `PENDING` ← not closed |
| `expected_date` | `2026-06-30` |
| `days_overdue` | `6` |
| `ordered_qty` | `200` |
| `received_qty` | `198` |
| `shortfall_qty` | `2` ← **the problem** |

**Why it's flagged:** 198 of 200 were received, leaving 2 outstanding, and 6 days past the expected
date the PO still hasn't been closed — Procurement needs to receive the balance or close it short.

---

## PO-09 · PO Missing Price

> **In one sentence:** find **closed** purchase-order lines (dated yesterday) that have **no vendor
> price** — blank or $0 — so the receipt against them can't be costed into the books.

### At a glance

| | |
|---|---|
| **Rule number** | PO-09 |
| **Rule type** | `NOT_NULL` (a "this field must not be blank/zero" check) |
| **Severity** | **Urgent** — same-day SLA |
| **Owner / routed team** | Procurement |
| **Default assignee** | Tom Becker |
| **Jira** | Project **WIQ** · Component **Vendor Pricing** |
| **Source table** | PO Table (`int_ledger_purchase_orders`) |
| **Live status** | 🟢 **Live — runs daily.** Flagged **0** on yesterday's data; it fires whenever a closed PO line dated that day is missing its vendor price. |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Purchase PO lines with no usable vendor (supplier) price — receipts can't be costed.
SELECT po, supplier_sku, consumable_sku, supplier_name, status, supplier_price, po_date_utc
FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
WHERE order_type = 'Purchase' AND (supplier_price IS NULL OR supplier_price = 0)
```

#### Live finder SQL (what runs daily)

```sql
-- CLOSED Purchase PO lines with a $0/NULL vendor price (can't be costed).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH flagged AS (
  SELECT po, supplier_sku,
         ANY_VALUE(po_source_system) AS system, ANY_VALUE(destination_name) AS facility,
         ANY_VALUE(supplier_name) AS supplier_name, ANY_VALUE(supplier_sku_name) AS supplier_sku_name,
         ANY_VALUE(status) AS status, MIN(supplier_price) AS supplier_price, MIN(po_date_utc) AS po_date_utc
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type='Purchase' AND (supplier_price IS NULL OR supplier_price = 0)
        AND supplier_sku IS NOT NULL AND UPPER(status)='CLOSED' AND DATE(po_date_utc)=run_date
  GROUP BY po, supplier_sku),
ranked AS (
  SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY po_date_utc DESC) AS rn
  FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 500 ORDER BY po_date_utc DESC
```

### Plain-English walkthrough

This rule reads a single table (the **PO Table**) — there's no join, because we're checking a field
on the purchase order itself, not comparing it to anything.

1. **`run_date` = yesterday.**

2. **`flagged` — find PO lines with no price.** From the PO Table, keep a line only when **all** of
   these are true:
   - `order_type = 'Purchase'` — it's an actual purchase (not a transfer).
   - `supplier_price IS NULL OR supplier_price = 0` — **the check**: the vendor price is blank *or*
     zero. Either way there's no real price to cost the receipt with.
   - `supplier_sku IS NOT NULL` — it's a real vendor line (ignore placeholder rows).
   - `UPPER(status) = 'CLOSED'` — **only closed POs.** An open PO might still get its price filled in
     before it's finalized, so flagging it early would be noise; once a PO is *closed* with no price,
     that's a genuine problem. (`UPPER(…)` just makes the match case-insensitive, so "Closed" and
     "CLOSED" both count.)
   - `DATE(po_date_utc) = run_date` — limit to POs dated yesterday (the daily batch).
   - `GROUP BY po, supplier_sku` — one row per PO line. `MIN(supplier_price)` is just a way to pull
     the single price value out after grouping.

3. **`ranked` + final line — count and cap.** Same plumbing as the other rules: stamp the total match
   count on every row, number them newest-first, keep the newest 500, drop the helper column.

### Tables & columns used

**Table:** PO Table — `int_ledger_purchase_orders`. **Joins:** none (single-table check).

| Column | Plain meaning | Role in this rule |
|---|---|---|
| `supplier_price` | The vendor's price for the line. | **The check** — flag when null or 0. |
| `order_type` | Purchase vs Transfer. | **Filter** — purchases only. |
| `status` | The PO's lifecycle status. | **Filter** — closed POs only. |
| `po_date_utc` | The PO's date. | **Filter** — yesterday; also sorts newest-first. |
| `supplier_sku` | The vendor's item number. | Identifies the line; must be present. |
| `po`, `supplier_name`, `supplier_sku_name` | PO number, vendor, item name. | Triage context on the ticket. |

### Example of a flagged record (from the dashboard)

A live exception currently open in the Workbench — **ERR-00058** (Jira **KAN-907**), routed to
Procurement:

| Field | Value |
|---|---|
| `po` | `VDC 4569` |
| `supplier_sku` / `supplier_sku_name` | `1347821` / `Tikka Sauce, Monsoon Kitchen (Staged) [Pouch, 340g]` |
| `supplier_name` | `US Foods Inc` |
| `supplier_price` | `$0.00` ← **the problem** |
| `po_date_utc` | `2026-06-09` |

**Why it's flagged:** the closed PO line carries no vendor price, so any receipt against it values at
$0 — understating inventory and COGS until Procurement sets the real vendor price.

---

## PO-11 · Correction Missing Ref ID

> **In one sentence:** find inventory-ledger **correction** transactions that don't say **which
> original transaction they're correcting** (a blank `correction_ref_id`), so the fix can't be traced.

### At a glance

| | |
|---|---|
| **Rule number** | PO-11 |
| **Rule type** | `NOT_NULL` (a "this field must not be blank" check, with an action filter) |
| **Severity** | **High** — 1-day SLA |
| **Owner / routed team** | SC Product (IMS) |
| **Default assignee** | Sarah Chen |
| **Jira** | Project **WIQ** · Component **Corrections** |
| **Source table** | The Inventory Ledger (`consolidated_inventory_ledger`) |
| **Grain** | **One ticket per ledger row** (each correction event). |
| **Key setting** | `po_correction_missing_ref_lookback_days` = **7** (only scan the last 7 days of ledger events; keeps the initial run small) |
| **Live status** | 🟢 **Live — runs daily.** Flagged **29** correction rows on the 2026-07-06 run (`KAN-1044`–`KAN-1072`). |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Framework PO-11: a ledger 'Correction' transaction (l1_action LIKE '%correct%') with a
-- NULL/blank correction_ref_id — the correcting entry doesn't reference what it fixes.
SELECT id, datetime_utc, facility_name, system_of_origin, l1_action, l2_action,
       consumable_sku, item_name, correction_ref_id
FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
WHERE LOWER(l1_action) LIKE '%correct%'
  AND (correction_ref_id IS NULL OR TRIM(correction_ref_id) = '')
```

#### Live finder SQL (what runs daily)

```sql
-- Ledger 'Correction' transaction (l1_action LIKE '%correct%') with no correction_ref_id
-- (framework PO-11), last 7 days. One row per ledger event.
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH flagged AS (
  SELECT CAST(id AS STRING) AS id, ANY_VALUE(facility_name) AS facility,
         ANY_VALUE(facility_type) AS facility_type, ANY_VALUE(system_of_origin) AS system,
         ANY_VALUE(consumable_sku) AS consumable_sku, ANY_VALUE(item_name) AS item_name,
         ANY_VALUE(l1_action) AS l1_action, ANY_VALUE(l2_action) AS l2_action,
         ANY_VALUE(ref_order_type) AS ref_order_type, ANY_VALUE(ref_order_id) AS ref_order_id,
         MIN(datetime_utc) AS datetime_utc
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE LOWER(l1_action) LIKE '%correct%'
    AND (correction_ref_id IS NULL OR TRIM(correction_ref_id) = '')
    AND DATE(datetime_utc) <= run_date
    AND DATE(datetime_utc) > DATE_SUB(run_date, INTERVAL 7 DAY)   -- last 7 days incl. run_date
  GROUP BY id),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY datetime_utc DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 500 ORDER BY datetime_utc DESC
```

### Plain-English walkthrough

This rule reads a single table — the **Inventory Ledger** — and checks one field on correction
transactions. No join: we're validating the correcting row against itself.

1. **`run_date` = yesterday.**

2. **`flagged` — find unreferenced corrections.** Keep a ledger row only when **all** are true:
   - `LOWER(l1_action) LIKE '%correct%'` — **the action filter**: the transaction's top-level action
     mentions "correct" (today that's `Correction`, e.g. *Correct Input Error*). `LOWER(…)` makes it
     case-insensitive, and the `%…%` wildcards catch "Correction", "Corrected", etc.
   - `correction_ref_id IS NULL OR TRIM(...) = ''` — **the check**: the correction carries no reference
     to the original transaction it's fixing.
   - `DATE(datetime_utc)` is within the **last 7 days** (up to and including `run_date`) — the recency
     window that keeps the first rollout small; the ledger is date-partitioned, so this also makes the
     query cheap. Widen `po_correction_missing_ref_lookback_days` to sweep more history.
   - `GROUP BY id` — one row per ledger transaction (`id` is the row's unique key); `ANY_VALUE`/`MIN`
     just pull the display fields out after grouping.

3. **`ranked` + final line — cap.** Stamp the total match count on every row, number them newest-first,
   keep the newest 500, drop the helper column.

**Auto-close:** each day the rule re-checks every open PO-11 ticket and closes it once that ledger
row's `correction_ref_id` has been populated.

### Tables & columns used

**Table:** The Inventory Ledger — `consolidated_inventory_ledger`. **Joins:** none (single-table check).

| Column | Plain meaning | Role in this rule |
|---|---|---|
| `l1_action` | The transaction's top-level action (Receipt, Adjust, Correction, …). | **Filter** — must contain "correct". |
| `correction_ref_id` | The id of the original transaction this entry corrects. | **The check** — flag when null/blank. |
| `datetime_utc` | When the transaction posted. | **Filter** — last 7 days; also sorts newest-first. |
| `id` | The ledger row's unique key. | Identity — one ticket per row; used to auto-close. |
| `l2_action`, `consumable_sku`, `item_name`, `facility_name`, `system_of_origin` | Sub-action, item, facility, source system. | Triage context on the ticket. |

### Example of a flagged record (from the dashboard)

A live exception opened by the 2026-07-06 run — **Jira KAN-1044**, routed to SC Product (IMS):

| Field | Value |
|---|---|
| `l1_action` / `l2_action` | `Correction` / `Correct Input Error` |
| `correction_ref_id` | *(blank)* ← **the problem** |
| `facility` | `DISH` |
| `consumable_sku` | `4000550` |
| `occurred_at` | `2026-07-06` |

**Why it's flagged:** the ledger records a correction to an input error, but it doesn't reference the
original transaction it corrects — so the fix can't be traced back or reconciled against what went
wrong.

---

## PO-13 · PO Table Missing PO Number

> **In one sentence:** find rows in the purchase-order **master table** that have **no PO number at
> all** — a broken master record with nothing to receive against.

### At a glance

| | |
|---|---|
| **Rule number** | PO-13 |
| **Rule type** | `NOT_NULL` (a "this field must not be blank" check) |
| **Severity** | **Urgent** — same-day SLA |
| **Owner / routed team** | SC Product (IMS) |
| **Default assignee** | Marcus Webb |
| **Jira** | Project **WIQ** · Component **PO Master Integrity** |
| **Source table** | PO Table (`int_ledger_purchase_orders`) |
| **Live status** | 🟢 **Live — safety-net.** Finds **0** on current data (every master PO row has a number); kept switched on so it catches the problem immediately if upstream ever degrades. PO-13 is the **PO-table twin of PO-01** (which checks the *ledger* side). |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Master PO table integrity: a Purchase row with no PO number (safety-net; 0 on current data).
SELECT _id, supplier_name, supplier_sku, consumable_sku, po_date_utc
FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
WHERE order_type = 'Purchase' AND (po IS NULL OR TRIM(po) = '')
```

#### Live finder SQL (what runs daily)

```sql
-- Purchase rows in the PO master with a NULL/blank PO number (safety-net).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH flagged AS (
  SELECT CAST(_id AS STRING) AS id, ANY_VALUE(supplier_name) AS supplier_name,
         ANY_VALUE(supplier_sku) AS supplier_sku, ANY_VALUE(consumable_sku) AS consumable_sku,
         MIN(po_date_utc) AS po_date_utc
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type='Purchase' AND (po IS NULL OR TRIM(po) = '') AND DATE(po_date_utc)=run_date
  GROUP BY id),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY po_date_utc DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 500
```

### Plain-English walkthrough

Same shape and logic as PO-01, but pointed at the **PO master table** instead of the ledger. Single
table, no join — we're just checking whether a field is blank.

1. **`run_date` = yesterday.**

2. **`flagged` — find master rows with no PO number.** From the PO Table, keep a row only when:
   - `order_type = 'Purchase'` — purchases only.
   - `po IS NULL OR TRIM(po) = ''` — **the check**: the PO-number field is empty, or only blank
     spaces (`TRIM` strips spaces so `"   "` counts as empty).
   - `DATE(po_date_utc) = run_date` — dated yesterday.
   - `GROUP BY id` — one row per master record (`_id` is the row's unique key — note the PO table uses
     **`_id`**, whereas the ledger uses `id`; they're different tables with different column names).

3. **`ranked` + final line — count, cap at 500, done.**

### Tables & columns used

**Table:** PO Table — `int_ledger_purchase_orders`. **Joins:** none (single-table check).

| Column | Plain meaning | Role in this rule |
|---|---|---|
| `po` | The purchase-order number. | **The check** — flag when null or blank. |
| `order_type` | Purchase vs Transfer. | **Filter** — purchases only. |
| `po_date_utc` | The PO's date. | **Filter** — yesterday; also sorts newest-first. |
| `_id` | Unique id for the PO master row. | Identifies the exact broken record to fix. |
| `supplier_name`, `supplier_sku`, `consumable_sku` | Vendor, vendor item, our item. | Triage context — what the orphaned row was for. |

### Example of a flagged record (illustrative)

| Field | Value |
|---|---|
| `_id` | `po_row_55e1a2` |
| `po` | *(blank)* ← **the problem** |
| `supplier_name` | `Sysco` |
| `consumable_sku` | `CSK-100884` |

**Why it's flagged:** a purchase-order master row with no PO number can't be received against or
matched to anything — it's a broken record that points to an upstream ingestion fault, so it's
**Urgent**.

---

## PO-14 · SKU Not on PO

> **In one sentence:** find items received yesterday against a **real** purchase order where that
> item **isn't actually listed on the PO** — a three-way-match break (wrong item, undocumented
> substitution, or a PO line that was never set up).

### At a glance

| | |
|---|---|
| **Rule number** | PO-14 |
| **Rule type** | `REFERENTIAL` (a "this value must exist in the other table" check) |
| **Severity** | **High** — 1-day SLA |
| **Owner / routed team** | SC Product (IMS) |
| **Default assignee** | Marcus Webb |
| **Jira** | Project **WIQ** · Component **3-Way Match** |
| **Source tables** | Inventory Ledger **⋈** PO Table (joined) |
| **Live status** | 🟢 **Live — runs daily.** Flagged **0** on yesterday's data; it fires whenever a SKU is received against a PO it isn't listed on. (This is the live version of framework catalog rule PO-02.) |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- 3-way match: a consumable_sku received against an existing PO (order_type='Purchase')
-- that is NOT on the PO's lines.
WITH led AS (
  SELECT DISTINCT ref_order_id AS po, consumable_sku
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type='Purchase Order' AND consumable_sku IS NOT NULL),
po_keys AS (SELECT DISTINCT po, consumable_sku FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders` WHERE order_type='Purchase'),
po_exists AS (SELECT DISTINCT po FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders` WHERE order_type='Purchase')
SELECT l.po, l.consumable_sku FROM led l JOIN po_exists pe USING (po)
LEFT JOIN po_keys pk ON l.po=pk.po AND l.consumable_sku=pk.consumable_sku
WHERE pk.po IS NULL  -- PO exists, but this received SKU isn't on it
```

#### Live finder SQL (what runs daily)

```sql
-- 3-way match: a consumable_sku received against an existing PO but not on its lines.
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH led AS (   -- items received against POs yesterday
  SELECT ref_order_id AS po, consumable_sku,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(system_of_origin) AS system,
         ANY_VALUE(item_name) AS item_name, ANY_VALUE(consumable_uom) AS ruom,
         SUM(consumable_quantity_change) AS received_qty,
         DATE(MIN(datetime_utc)) AS first_receipt_date, DATE(MAX(datetime_utc)) AS last_receipt_date,
         ANY_VALUE(l1_action HAVING MAX consumable_quantity_change) AS move_l1,
         ANY_VALUE(l2_action HAVING MAX consumable_quantity_change) AS move_l2
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type='Purchase Order' AND consumable_sku IS NOT NULL AND DATE(datetime_utc)=run_date
  GROUP BY po, consumable_sku),
po_keys AS (   -- every (PO, item) that IS on a purchase order's lines
  SELECT DISTINCT po, consumable_sku FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type='Purchase' AND consumable_sku IS NOT NULL),
po_exists AS (   -- POs that actually exist
  SELECT po, ANY_VALUE(supplier_name) AS supplier FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type='Purchase' GROUP BY po),
flagged AS (
  SELECT l.*, pe.supplier
  FROM led l JOIN po_exists pe USING (po)                 -- the PO is real …
  LEFT JOIN po_keys pk ON l.po=pk.po AND l.consumable_sku=pk.consumable_sku
  WHERE pk.po IS NULL),                                   -- … but this item isn't on it
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches,
                  ROW_NUMBER() OVER (ORDER BY last_receipt_date DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 500 ORDER BY last_receipt_date DESC
```

### Plain-English walkthrough

This rule answers: *"we received this item against PO #12345 — but was this item ever actually
ordered on PO #12345?"* That needs both tables: the **ledger** (what was received) and the **PO
table** (what was ordered). It's built in named steps.

1. **`run_date` = yesterday.**

2. **`led` — what got received against POs yesterday.** From the ledger, one row per (PO, item)
   received yesterday, with the net quantity and triage details (facility, system, item name, the
   dominant receiving action, first/last receipt dates).

3. **`po_keys` — the "allowed" list.** Every (PO, item) combination that **is** on a purchase order's
   lines. Think of this as the guest list: which items each PO actually ordered.

4. **`po_exists` — which POs are real.** The set of PO numbers that exist at all (plus the supplier).

5. **`flagged` — the match logic (this is the clever part).** Two joins do the work:
   - `JOIN po_exists … USING (po)` — first confirm the **PO is real**. (If the PO itself didn't
     exist, that's a *different* problem — a missing PO, not a wrong item — so we require it to exist
     here.)
   - `LEFT JOIN po_keys … ON po AND consumable_sku` then **`WHERE pk.po IS NULL`** — this is the key
     trick, called an *anti-join*. A `LEFT JOIN` tries to find a matching row in the guest list
     (`po_keys`) for this received item; if it finds one, the `pk.*` columns are filled in; if it
     finds **none**, they come back empty (`NULL`). So `WHERE pk.po IS NULL` keeps exactly the
     receipts **where the item was *not* found on the PO** — i.e. the three-way-match breaks. In plain
     terms: "the PO is real, but this item isn't on its guest list."

6. **`ranked` + final line — count, cap at 500, newest-first.**

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** PO Table (`int_ledger_purchase_orders`).
**Join keys:** `ref_order_id` ⇄ `po` (the order) and `consumable_sku` ⇄ `consumable_sku` (the item).

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `ref_order_id` (ledger) | The PO the receipt was booked against. | **Join key** — must exist in the PO table. |
| `consumable_sku` (ledger) | The item that was received. | **The check** — must appear on that PO's lines. |
| `datetime_utc` (ledger) | When it was received. | **Filter** — yesterday; sets the receipt dates. |
| `consumable_quantity_change` (ledger) | Quantity received. | Net received qty shown on the ticket. |
| `po`, `consumable_sku` (PO) | The order's lines (what was ordered). | The "guest list" the received item is matched against. |
| `supplier_name` (PO) | Vendor on the PO. | Triage context. |

### Example of a flagged record (from the dashboard)

A live exception currently open in the Workbench — **ERR-00048** (Jira **KAN-897**), routed to
SC Product (IMS):

| Field | Value |
|---|---|
| `po` | `127308375` (exists ✓) |
| `consumable_sku` / `item_name` | `9001847` / `Clamshell, Fred's, Burger Box` |
| On the PO's lines? | **No** ← **the problem** |
| `received_qty` | `800 ea` |
| `supplier` / `facility` | `Ed Don` / `Hackettstown` |
| First → last receipt | `2026-06-11` |

**Why it's flagged:** the PO is valid, but this item was never ordered on it — likely a wrong item
received, an undocumented substitution, or a PO line that was never set up. It needs reconciliation
before the receipt is trusted, hence **High**.

---

<!-- ───────────────────────────────────────────────────────────────────────────
     A note on the two COST rules: both compare items to the ERP standard-cost table.
     COST-01 = the item has NO cost record at all. COST-02 = it HAS one, but it's $0/NULL.
     ─────────────────────────────────────────────────────────────────────────── -->

> **The two cost rules, side by side.** Both check an item against the **ERP standard-cost table**,
> but for opposite failures. **COST-01** fires when the item has **no cost record at all** (it's
> missing from the ERP), so its waste can't be valued. **COST-02** fires when the item **has a cost
> record, but the cost is $0 or blank**, so every dollar figure for it comes out wrong. In SQL terms
> that's the difference between a `LEFT JOIN … WHERE cost IS NULL` (COST-01: no match found) and a
> `JOIN … WHERE cost = 0` (COST-02: match found, but the value is bad).

### Where the standard cost comes from

Both rules need the **official cost of each item**, which doesn't live in the inventory warehouse —
it lives in the **ERP (Microsoft Dynamics)**, a separate system in its own project
(`wonder-raw-prod.erp_prod_batch`). In every cost-rule query, the first step (a slice named `cost`)
builds a clean one-row-per-item price list from the ERP: for each item (`ITEMID`) it takes the
**most recently activated price** at the company's `'control'` costing site and computes a
per-unit cost (`unit_cost = PRICE ÷ PRICEUNIT`). The item is linked to our inventory by matching the
ERP's `ITEMID` to our `consumable_sku`. The `cost` step is **identical in both rules below**, so it's
explained once here and not repeated in each walkthrough.

---

## COST-01 · Waste SKU Without Cost

> **In one sentence:** find items that were **wasted or adjusted** yesterday but have **no standard
> cost set up at all** in the ERP — so their waste can't be valued and silently disappears from the
> waste-dollar totals.

### At a glance

| | |
|---|---|
| **Rule number** | COST-01 |
| **Rule type** | `RECONCILIATION` (a "these two systems must agree" check — here, ledger activity vs the ERP cost list) |
| **Severity** | **High** — 1-day SLA |
| **Owner / routed team** | Accounting (Cost Accountant) |
| **Default assignee** | Mike Dietrich |
| **Jira** | Project **WIQ** · Component **Standard Cost** |
| **Source tables** | Inventory Ledger **⋈** ERP standard-cost table |
| **Live status** | 🟢 **Live — runs daily.** Flagged **1** on yesterday's data; it fires whenever a wasted item has no ERP cost record. |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- A consumable_sku with waste/adjust activity that has NO row in the ERP standard-cost table
-- (ITEMID), so its waste can't be valued. LEFT JOIN waste-active SKUs -> cost; flag the misses.
SELECT w.consumable_sku FROM (waste-active consumable_sku) w
LEFT JOIN (erp standard cost, ITEMID) c ON CAST(w.consumable_sku AS STRING) = c.ITEMID
WHERE c.ITEMID IS NULL
```

*(The two parenthesized inputs are spelled out in full in the live query below — `waste` and `cost`.)*

#### Live finder SQL (what runs daily)

```sql
-- Waste-active consumable_sku with NO ERP standard-cost record (no ITEMID match).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH cost AS (   -- latest-activated ERP standard cost per item (see "Where the standard cost comes from")
  SELECT ITEMID, AVG(UnitPrice) AS unit_cost, ANY_VALUE(UNITID) AS cost_uom FROM (
    SELECT p.ITEMID, SAFE_DIVIDE(p.PRICE, p.PRICEUNIT) AS UnitPrice, p.UNITID
    FROM `wonder-raw-prod.erp_prod_batch.inventitempriceftistaging` AS p
    INNER JOIN (
      SELECT MAX(price.ActivationDate) AS ActivationDate, MAX(price.CREATEDTIME) AS CREATEDTIME,
             price.ITEMID, price.INVENTDIMID, price.DATAAREAID
      FROM `wonder-raw-prod.erp_prod_batch.inventitempriceftistaging` AS price
      INNER JOIN `wonder-raw-prod.erp_prod_batch.inventdimftistaging` AS dim
        ON dim.INVENTDIMID = price.INVENTDIMID AND LOWER(dim.INVENTDIMDATAAREAID) = LOWER(price.DATAAREAID)
        AND LOWER(dim.INVENTSITEID) = 'control'
      GROUP BY price.ITEMID, price.DATAAREAID, price.INVENTDIMID
    ) m ON m.ITEMID = p.ITEMID AND m.ActivationDate = p.ActivationDate AND m.CREATEDTIME = p.CREATEDTIME
       AND LOWER(m.INVENTDIMID) = LOWER(p.INVENTDIMID) AND LOWER(m.DATAAREAID) = LOWER(p.DATAAREAID))
  GROUP BY ITEMID),
waste AS (   -- items with waste/adjustment activity yesterday, and how much was lost
  SELECT consumable_sku, ANY_VALUE(item_name) AS item_name, ANY_VALUE(consumable_uom) AS consumable_uom,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(facility_type) AS facility_type,
         ANY_VALUE(system_of_origin) AS system,
         SUM(IF(consumable_quantity_change < 0, -consumable_quantity_change, 0)) AS waste_qty,
         DATE(MIN(datetime_utc)) AS first_seen, DATE(MAX(datetime_utc)) AS last_seen
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE l1_action = 'Adjust'
    AND l2_action NOT IN ('Move From','Move To','Update Received Order','Shelf Life Extension')
    AND consumable_sku IS NOT NULL AND DATE(datetime_utc) = run_date
  GROUP BY consumable_sku),
flagged AS (   -- keep the wasted items with NO cost record
  SELECT w.* FROM waste w
  LEFT JOIN cost c ON CAST(w.consumable_sku AS STRING) = c.ITEMID
  WHERE c.ITEMID IS NULL),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY waste_qty DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked ORDER BY waste_qty DESC
```

### Plain-English walkthrough

1. **`run_date` = yesterday.**

2. **`cost` — the ERP price list.** One row per item with its latest standard cost (explained in
   *"Where the standard cost comes from"* above).

3. **`waste` — what was wasted/adjusted yesterday.** From the ledger, keep only **adjustment**
   movements (`l1_action = 'Adjust'`) that represent genuine inventory loss — *excluding* the
   `l2_action`s that are just location moves or admin corrections (`Move From`, `Move To`,
   `Update Received Order`, `Shelf Life Extension`). For each item it sums the **quantity lost**
   (`SUM` of the negative movements, flipped to a positive `waste_qty`).

4. **`flagged` — the items with no cost on file.** A `LEFT JOIN` tries to find each wasted item in the
   `cost` list; **`WHERE c.ITEMID IS NULL`** keeps only the ones where **no cost row was found** — the
   same anti-join trick as PO-14, but here it means "this item isn't set up in the ERP cost table at
   all."

5. **`ranked` + final line — order by biggest loss.** It stamps the total match count on each row and
   sorts by `waste_qty` (largest waste first). Note this rule is **not capped** — every such item is
   surfaced, because each one is a hole in the waste valuation.

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** ERP standard cost
(`wonder-raw-prod.erp_prod_batch.inventitempriceftistaging`). **Join key:** `consumable_sku` ⇄ `ITEMID`.

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `l1_action` / `l2_action` (ledger) | The movement's action / sub-action. | **Filter** — keep waste adjustments, drop moves & admin corrections. |
| `consumable_quantity_change` (ledger) | How much the item moved (− = loss). | Summed into `waste_qty` (the amount lost). |
| `consumable_sku` (ledger) | The item that was wasted. | **Join key** to the ERP cost list. |
| `ITEMID` (ERP) | The ERP's item id. | **Join key** — its **absence** is the failure. |
| `datetime_utc` (ledger) | When it happened. | **Filter** — yesterday; first/last seen dates. |
| `facility_name` (ledger) | Where the waste occurred. | Triage context. |

### Example of a flagged record (from the dashboard)

A live exception currently open in the Workbench — **ERR-00039** (Jira **KAN-888**), routed to
Accounting:

| Field | Value |
|---|---|
| `consumable_sku` / `item_name` | `5182961` / `Chicken Wonton, FC (Buyout)` |
| `waste_qty` (over the window) | `11,361.21 lb` |
| Cost record in ERP? | **None** ← **the problem** |
| `facility` (type) | `CK1` (Production) |
| First → last seen | `2026-05-30` → `2026-06-12` |

**Why it's flagged:** 11,361 lb of this item was wasted/adjusted over the window, but with no standard
cost on file that waste values at **$0** in every report — silently understating total waste.
Accounting needs to set up a standard cost for the item in Dynamics.

---

## COST-02 · Consumable Missing Cost

> **In one sentence:** find items active in the ledger yesterday that **have** a standard-cost record
> but whose cost is **$0 or blank** — so every dollar figure for them (waste, on-hand, COGS) comes out
> wrong.

### At a glance

| | |
|---|---|
| **Rule number** | COST-02 |
| **Rule type** | `RECONCILIATION` (ledger activity vs the ERP cost list) |
| **Severity** | **High** — 1-day SLA |
| **Owner / routed team** | Accounting (Cost Accountant) |
| **Default assignee** | Mike Dietrich |
| **Jira** | Project **WIQ** · Component **Standard Cost** |
| **Source tables** | Inventory Ledger **⋈** ERP standard-cost table |
| **Live status** | 🟢 **Live — runs daily.** Flagged **4** on yesterday's data. There's a large standing backlog (600+ items); the daily run tickets a **sample of up to 5** of the day's active zero-cost items while the program works through it. |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Framework #66: a consumable_sku active in the ledger whose ERP standard cost (PRICE/PRICEUNIT)
-- is 0 or NULL — can't be costed. JOIN ledger SKUs -> cost; flag unit_cost IS NULL OR = 0.
SELECT l.consumable_sku, c.unit_cost FROM (ledger consumable_sku) l
JOIN (erp standard cost) c ON CAST(l.consumable_sku AS STRING) = c.ITEMID
WHERE c.unit_cost IS NULL OR c.unit_cost = 0
```

#### Live finder SQL (what runs daily)

```sql
-- Ledger-active consumable_sku whose ERP standard cost is 0/NULL (sample of 5 of the 600+ backlog).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH cost AS (   -- latest-activated ERP standard cost per item (identical to COST-01's `cost` step)
  SELECT ITEMID, AVG(UnitPrice) AS unit_cost, ANY_VALUE(UNITID) AS cost_uom FROM (
    SELECT p.ITEMID, SAFE_DIVIDE(p.PRICE, p.PRICEUNIT) AS UnitPrice, p.UNITID
    FROM `wonder-raw-prod.erp_prod_batch.inventitempriceftistaging` AS p
    INNER JOIN (
      SELECT MAX(price.ActivationDate) AS ActivationDate, MAX(price.CREATEDTIME) AS CREATEDTIME,
             price.ITEMID, price.INVENTDIMID, price.DATAAREAID
      FROM `wonder-raw-prod.erp_prod_batch.inventitempriceftistaging` AS price
      INNER JOIN `wonder-raw-prod.erp_prod_batch.inventdimftistaging` AS dim
        ON dim.INVENTDIMID = price.INVENTDIMID AND LOWER(dim.INVENTDIMDATAAREAID) = LOWER(price.DATAAREAID)
        AND LOWER(dim.INVENTSITEID) = 'control'
      GROUP BY price.ITEMID, price.DATAAREAID, price.INVENTDIMID
    ) m ON m.ITEMID = p.ITEMID AND m.ActivationDate = p.ActivationDate AND m.CREATEDTIME = p.CREATEDTIME
       AND LOWER(m.INVENTDIMID) = LOWER(p.INVENTDIMID) AND LOWER(m.DATAAREAID) = LOWER(p.DATAAREAID))
  GROUP BY ITEMID),
led AS (   -- every item active in the ledger yesterday
  SELECT consumable_sku, ANY_VALUE(item_name) AS item_name, ANY_VALUE(consumable_uom) AS consumable_uom,
         ANY_VALUE(facility_name) AS facility, ANY_VALUE(facility_type) AS facility_type,
         ANY_VALUE(system_of_origin) AS system, DATE(MAX(datetime_utc)) AS last_seen
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE consumable_sku IS NOT NULL AND DATE(datetime_utc) = run_date
  GROUP BY consumable_sku),
flagged AS (   -- items that HAVE a cost record, but the cost is 0/NULL
  SELECT l.*, c.unit_cost, c.cost_uom
  FROM led l JOIN cost c ON CAST(l.consumable_sku AS STRING) = c.ITEMID
  WHERE c.unit_cost IS NULL OR c.unit_cost = 0),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY last_seen DESC) AS rn FROM flagged)
SELECT * EXCEPT(rn) FROM ranked WHERE rn <= 5 ORDER BY last_seen DESC
```

### Plain-English walkthrough

The shape mirrors COST-01, with **one crucial difference in the join** (see below).

1. **`run_date` = yesterday.**

2. **`cost` — the ERP price list.** Identical to COST-01's `cost` step.

3. **`led` — every item active in the ledger yesterday.** Any item that had *any* movement that day
   (not just waste), one row each.

4. **`flagged` — items whose cost exists but is zero.** Here it's a plain **`JOIN`** (not a `LEFT
   JOIN`): the item **must** be found in the `cost` list — i.e. it **has** a cost record — **and then**
   `WHERE c.unit_cost IS NULL OR c.unit_cost = 0` keeps only the ones whose cost is **blank or zero**.
   This is the exact opposite of COST-01: COST-01 fires when there's *no* record; COST-02 fires when
   there *is* one but it's worthless.

5. **`ranked` + final line — sample the backlog.** Because there's a large standing backlog, the daily
   run keeps only the **5 most recently active** (`WHERE rn <= 5`) so it tickets a representative
   sample rather than flooding the queue; `total_matches` still records how many there really were.

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** ERP standard cost
(`wonder-raw-prod.erp_prod_batch.inventitempriceftistaging`). **Join key:** `consumable_sku` ⇄ `ITEMID`.

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `consumable_sku` (ledger) | An item active in inventory. | **Join key** to the ERP cost list. |
| `datetime_utc` (ledger) | When it last moved. | **Filter** — active yesterday; sorts the sample. |
| `ITEMID` (ERP) | The ERP's item id. | **Join key** — must exist (record present). |
| `unit_cost` (ERP, derived) | The item's standard cost (PRICE ÷ PRICEUNIT). | **The check** — flag when null or 0. |
| `item_name`, `facility_name` (ledger) | Item name, facility. | Triage context. |

### Example of a flagged record (from the dashboard)

A live exception currently open in the Workbench — **ERR-00044** (Jira **KAN-893**), routed to
Accounting:

| Field | Value |
|---|---|
| `consumable_sku` / `item_name` | `4000981` / `Fresh Bean Sprouts (4 oz)` |
| Cost record in ERP? | **Yes**, but… |
| `standard_unit_cost` | `$0.00` ← **the problem** |
| `facility` (type) | `Reston` (HDR) |
| `last_seen` | `2026-06-28` |

**Why it's flagged:** the item is set up in the ERP, but its standard cost is $0 — so its waste,
on-hand value, and COGS all calculate to zero. Accounting needs to correct the standard cost in
Dynamics. (One of 600+ in the standing backlog; a daily sample is ticketed.)

---

<!-- ───────────────────────────────────────────────────────────────────────────
     REMAINING RULES — to be authored. Each follows the identical six-part structure.
     ─────────────────────────────────────────────────────────────────────────── -->

## Coverage tracker — all rules

Where each rule stands, and whether it's been written up in this guide yet.

**Status legend:** 🟢 **Live** = enabled *and* its detection query is wired in, so it runs daily and
creates tickets · 🟡 **Catalog-only** = enabled but no detection query is wired yet, so it silently
finds nothing · ⚪ **Paused** = query exists but the rule is toggled off.

| Rule | Error type | Status | Documented here |
|---|---|---|---|
| PO-01 | Inventory Log Missing PO Number | 🟢 Live | ✅ |
| PO-02 | PO Record Missing | 🟡 Catalog-only (orphan-PO check; PO-14 covers the live case) | — (catalog) |
| PO-03 | PO Over Receipt | 🟢 Live | ✅ |
| PO-07 | PO Overdue — No Receipt | 🟢 Live | ✅ |
| PO-08 | PO Partially Received — Not Closed | 🟢 Live | ✅ |
| PO-09 | PO Missing Price | 🟢 Live | ✅ |
| PO-11 | Correction Missing Ref ID | 🟢 Live | ✅ |
| PO-13 | PO Table Missing PO Number | 🟢 Live | ✅ |
| PO-14 | SKU Not on PO | 🟢 Live | ✅ |
| TWH-01 | Transfer Warehouse Imbalance (WIP) | 🟡 Catalog-only (needs transfer-order pairing) | — (catalog) |
| XFER-01 | Transfer Order Missing (WIP) | ⚪ Paused (transfer work on hold) | — |
| COMPLETE-02 | Negative On-Hand | 🟡 Catalog-only (needs cumulative cross-day balance) | — (catalog) |
| WASTE-DAILY | Daily Waste (Facility) | 🟢 Live | ◻ to do |
| ADJ-DAILY | Daily Adjustments (Facility) | 🟢 Live | ◻ to do |
| COST-01 | Waste SKU Without Cost | 🟢 Live | ✅ |
| COST-02 | Consumable Missing Cost | 🟢 Live | ✅ |

The PO family and both cost rules are fully documented above. Still **to do** (live, not yet written
up): the two daily facility-dollar rules — **WASTE-DAILY** and **ADJ-DAILY**. The **catalog-only**
rules (PO-02, TWH-01, COMPLETE-02) and the **paused** XFER-01 will be written up when their detectors
are wired / work resumes.
