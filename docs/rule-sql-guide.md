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
| **Jonny Signoff** | 2026-07-15 |
| **Live status** | ✅ **Live — runs in the daily validation job, and it fires.** Identifying receipts by their movement action surfaces a real, ongoing problem: **Fishbowl / facility CK1** receipts land with both `ref_order_type` and the PO number blank (~13 in the last 30 days; 16–40/month for the past 8 months). The prior version keyed on `ref_order_type = 'Purchase Order'` and matched **0 rows in all of history** — it was watching the wrong column and missed every one of these. The filter covers both receipt actions — `'PO Receipt'` (Fishbowl/Extensiv/Shiphero/RMX) and Pantry's `'Received'` — so every source system's receipts are checked. |

### The SQL

The two versions below do **the same check** — they differ only in plumbing. The catalog version is
the plain-English-friendly statement of the rule; the live version is what the daily job actually
runs and is what you see in the Admin → Rule editor.

#### Catalog SQL (the documented definition)

```sql
-- A PO-receipt row (identified by its movement action) that carries no PO id (ref_order_id NULL/blank).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

SELECT
  id,
  datetime_utc,
  facility_name,
  system_of_origin,
  l1_action,
  l2_action,
  consumable_sku,
  item_name,
  ref_order_type,
  ref_order_id
FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
WHERE (l2_action = 'PO Receipt' OR (l2_action = 'Received' AND system_of_origin = 'Pantry'))
  AND (ref_order_id IS NULL OR TRIM(ref_order_id) = '')
  AND DATE(datetime_utc) = run_date
ORDER BY datetime_utc DESC
```

#### Live finder SQL (what runs daily)

```sql
-- A PO-order-type receiving row in the ledger with a NULL/blank PO number (safety-net).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- daily batch target = the just-closed day (yesterday PST in prod)

WITH flagged AS (
  SELECT CAST(id AS STRING) AS id, ANY_VALUE(facility_name) AS facility,
         ANY_VALUE(system_of_origin) AS system, ANY_VALUE(consumable_sku) AS consumable_sku,
         ANY_VALUE(item_name) AS item_name, ANY_VALUE(l1_action) AS l1_action,
         ANY_VALUE(l2_action) AS l2_action, ANY_VALUE(ref_order_type) AS ref_order_type,
         MIN(datetime_utc) AS datetime_utc
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE (l2_action = 'PO Receipt' OR (l2_action = 'Received' AND system_of_origin = 'Pantry'))
    AND (ref_order_id IS NULL OR TRIM(ref_order_id) = '') AND DATE(datetime_utc) = run_date
  GROUP BY id),
ranked AS (SELECT *, COUNT(*) OVER() AS total_matches, ROW_NUMBER() OVER (ORDER BY datetime_utc DESC) AS rn FROM flagged)
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
- `WHERE (l2_action = 'PO Receipt' OR (l2_action = 'Received' AND system_of_origin = 'Pantry'))` — keep only **purchase-order receipts** (inventory arriving because we bought it), identified by the **movement action**. We deliberately key on the *action* and not on `ref_order_type = 'Purchase Order'`: on exactly the broken rows this rule exists to catch, `ref_order_type` is itself blank, so keying on it would let those receipts slip through. The movement action stays populated even when the reference fields don't. Two action labels are in play across the source systems — `'PO Receipt'` (Fishbowl, Extensiv, Shiphero, RMX) and `'Received'` (Pantry) — so we cover both. The `'Received'` arm is **scoped to Pantry** on purpose: a different source, `system_of_origin = 'System'`, also emits `'Received'` for internal negative-quantity depletion/reversal entries that are almost never PO-linked, and pulling those in would flood this Urgent queue with false positives.
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
**newest-first**. On a normal day there are far fewer than 500 matches — currently on the order of a
handful per week (the Fishbowl / CK1 blank-PO receipts).

### Tables & columns used

**Table:** The Inventory Ledger — `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`

| Column | Plain meaning | Role in this rule |
|---|---|---|
| `l2_action` | The movement's sub-action (e.g. *PO Receipt*, *Received*, *Transfer Out*). | **Filter** — keep `PO Receipt` rows, plus `Received` rows from Pantry (identifies a PO receipt by its action). |
| `system_of_origin` (in filter) | The upstream system the record came from. | **Filter** — scopes the `Received` arm to Pantry, excluding `System`-origin depletion/reversal noise. |
| `ref_order_id` | The purchase-order number the receipt belongs to. | **The check** — flag when this is null or blank. |
| `datetime_utc` | Exact UTC timestamp of the movement. | **Filter** — keep only yesterday; also sort newest-first. |
| `id` | Unique id for the Inventory Ledger row. | Identifies the exact record to fix; used as the ticket fingerprint. |
| `facility_name` | Which facility recorded the movement. | Triage — tells the owner *where* it happened. |
| `system_of_origin` | The upstream system the record came from (Pantry / Ship Hero / Fishbowl / Extensiv / RMX). | Triage — points to where the data was entered. |
| `ref_order_type` | What kind of order the movement relates to (e.g. *Purchase Order*). | Context/snapshot only — on the flagged rows this is typically **blank**, which is why the rule keys on `l2_action` instead. |
| `l1_action` | The movement's action category (e.g. *Add*). | Context — what kind of movement this was. |
| `consumable_sku` | The item identifier (SKU) involved. | Triage — *what* item came in. |
| `item_name` | Human-readable item name. | Triage — the item in plain words. |

### Example of a flagged record (real)

> This is a **real** row the rule catches on live data (Fishbowl / CK1, recorded 2026-07-13). It is a
> PO receipt — the movement action says so — but it arrived with **both** the PO number *and* the
> `ref_order_type` blank, which is exactly why the rule keys on `l2_action` rather than `ref_order_type`.

| Column | Value |
|---|---|
| `id` | `1c13ad9a6689c9b34a567d2936c7a4d9` |
| `datetime_utc` | `2026-07-13 13:53:39 UTC` |
| `facility_name` | `CK1` |
| `system_of_origin` | `Fishbowl` |
| `l1_action` / `l2_action` | `Add` / `PO Receipt` |
| `consumable_sku` | `5001001` |
| `item_name` | `Red Pepper Flakes, Crushed, Bulk` |
| `ref_order_type` | *(blank)* ← why keying on `ref_order_type = 'Purchase Order'` missed it |
| `ref_order_id` | *(blank)* ← **the problem** |

**Why it's flagged:** its movement action marks it a purchase-order receipt, but with no PO number we
can't match it to what was ordered, can't validate quantity or price, and can't close out the PO —
hence the **Urgent** severity and same-day SLA.

> **Coverage note (for the data team).** Two receipt-action labels are in play across the source
> systems: `'PO Receipt'` (Fishbowl, Extensiv, Shiphero, RMX) and `'Received'` (Pantry, ≈22k rows in
> the last 30 days, all currently carrying a PO number). The filter covers both, but scopes the
> `'Received'` arm to **Pantry** — `system_of_origin = 'Pantry'`. That scope is deliberate: a separate
> source, `system_of_origin = 'System'`, *also* emits `l2_action = 'Received'`, but for **internal
> negative-quantity depletion/reversal entries** that are almost never PO-linked (2 of 437 rows over
> 90 days carried a PO). Those are not purchase-order receipts, so including them would generate ~40
> false-positive Urgent tickets a month. If `'System'` is ever confirmed to be a real receiving flow
> that *should* carry PO numbers, drop the Pantry scope to bring it in. There is also a rare Pantry
> variant, `'Received with Other Quality Issue'`; it's not in the filter — reopen this note if it ever
> starts arriving with blank PO numbers.

---

## PO-03 · PO Over Receipt

> **In one sentence:** find purchase orders that received stock where **more came in than was
> ordered** — checked **two independent ways** (the PO's own receipt count *and* the inventory
> ledger's cumulative receipts) so we catch it whether the discrepancy shows up on the buying side,
> the warehouse side, or both.

### 📝 Change note — for data-analyst sign-off (Jonny Li)

> **Status: awaiting sign-off.** This documents a July 2026 refinement of PO-03. It reflects Jonny's
> two directions — (1) re-base off the **IMS SKU** rather than the translated *consumable* SKU, and
> (2) make it a **two-way match** (the PO's own receipt count *and* the ledger cumulative) — plus two
> deviations from the literal instruction that the live data forced (see ⚠️ below).

**What changed**

| | Before | After |
|---|---|---|
| **Item key / grain** | `consumable_sku` (a downstream translation) | **`ims_sku`** (raw id on both tables); one ticket per `(PO, IMS SKU)` |
| **Signals** | one — ledger receipts vs ordered | **two** — Layer 1: PO's own `received_qty` vs `ims_sku_qty` (packaging); Layer 2: ledger `SUM(ims_quantity_change)` vs `consumable_sku_qty` (base) |
| **Flag condition** | ledger over by >30% (or UoM mismatch) | **either** layer over by >30% (or UoM mismatch) |
| **Threshold** | 30% High / 100% Urgent | unchanged (30% / 100%) |

**Why — evidence from live prod data**

1. **Consumable was the noise source, not the base unit.** Keeping the same base-unit comparison but
   re-keying it from `consumable_sku` to `ims_sku` dropped the over-receipt count **≈109 → ≈34** on a
   recent 45-day window — the translation was fanning one order across rows. This is Jonny's exact
   point, confirmed.
2. **The two layers genuinely diverge, in one direction.** Over ~2,281 recently-touched pairs, every
   PO-books over-receipt is *also* a ledger over-receipt (PO-only = 0), and the ledger catches extra
   **ledger-only** cases where the PO's own count looks clean — the case the single-signal rule missed
   (see the `PO 61920` Roncadin example below).

**⚠️ Two deviations from the literal instruction, both data-forced**

The instruction was to use IMS quantities on both sides. On the ledger that isn't fully viable, so
**Layer 2 splits its two jobs across two different ledger columns**:

- **Deciding whether a pair is over** (the `led_received` total compared to `consumable_sku_qty`) sums
  `ims_quantity_change`, not `consumable_quantity_change`. An earlier pass used
  `consumable_quantity_change` for this total; Jonny's follow-up flagged that basis as over-flagging on
  live data, so the received total now runs on `ims_quantity_change` instead.
- **Timestamping when it started** (the `breach` CTE's running total, used only to find the first
  receipt that crossed the threshold) still sums `consumable_quantity_change`. That's a lower-stakes use
  — pinpointing *when* the total crossed the line, not deciding *whether* it did — where the two
  columns' ~90% agreement is good enough.
- Ledger `ims_quantity_change` is stored in the **base** unit — it equals `consumable_quantity_change`
  ~90% of rows, and for the same IMS SKU the ledger's `ims_uom` matches the PO's `ims_uom` only ~5% of
  the time. So it still can't be compared to PO `ims_sku_qty` (Layer 1's packaging-unit benchmark) —
  it stays a Layer 2 (base-unit) measure, just a different base-unit column than originally documented.
- Ledger `supplier_quantity_change` *is* in packaging units but is **NULL for 100% of Pantry
  receipts** (the largest receiving flow), so it can't be used universally either.

*Confirmed live — this is the column the finder SQL actually runs on (see below).*

### At a glance

| | |
|---|---|
| **Rule number** | PO-03 |
| **Rule type** | `RANGE` (a "the value must stay within an expected range" check — here, received vs ordered), evaluated as a **two-way match** |
| **Grain** | **One ticket per (PO, IMS SKU)** — was per (PO, consumable SKU). |
| **Severity** | **Banded by how far over:** 30–99% over → **High** (a supply-chain signal, e.g. an over-shipment); ≥100% over (received ≥ 2× ordered) → **Urgent** (a likely receiving error like a double-scan). A pure unit-of-measure mismatch (neither layer over) is split off as its own error type (`PO_UOM_MISMATCH`). |
| **Owner / routed team** | Field Ops |
| **Default assignee** | Diego Alvarez |
| **Jira** | Project **WIQ** · Component **Receiving** |
| **Source tables** | Inventory Ledger **⋈** PO Table (joined on `ref_order_id` ⇄ `po` and **`ims_sku`** ⇄ `ims_sku`) |
| **Jonny Signoff** | 2026-07-17 |
| **Live status** | 🟢 **Live — runs daily.** Flagged **0** on 2026-07-13 (no over-receipts booked that day); a 14-day backfill window catches **5**, all confirmed by *both* layers. It fires whenever a PO's own receipts **or** its ledger cumulative cross the over-receipt threshold. |

### Why two layers — and why IMS, not consumable

The two tables record receiving in **different units**, and this is the crux of the refinement:

- The **PO table** books both what was ordered (`ims_sku_qty`) and its own running received count
  (`received_qty`) in the **vendor packaging unit** — cases, packs, eaches (`cs` / `pk` / `ea`).
- The **inventory ledger** books each movement in the **base/consumable unit** — ounces, pounds,
  grams. Confirmed on live data: `ims_quantity_change` on the ledger equals `consumable_quantity_change`
  ~90% of the time (both base units), and for the *same* IMS SKU the ledger's `ims_uom` matches the
  PO's `ims_uom` only ~5% of the time. So the ledger's "IMS quantity" is **not** in the PO's IMS
  packaging unit — comparing them directly would produce nonsense (e.g. 50 cases ordered vs 8,400 oz
  received → a fake 168× "over-receipt"). It's still a base-unit column, though, so it can stand in
  for `consumable_quantity_change` as Layer 2's received total (see the ⚠️ note above for why it does).

So each layer is measured **entirely within its own unit system**, never across the base↔packaging
boundary:

| Layer | Ordered | Received | Unit |
|---|---|---|---|
| **1 · PO's own books** | `ims_sku_qty` | `received_qty` | packaging (`cs`/`pk`/`ea`) — one table, no conversion |
| **2 · Ledger cumulative** | `consumable_sku_qty` | `SUM(ims_quantity_change)` | base (`oz`/`lb`/`g`) — the only cross-system-reliable ledger measure |

Layer 2's received total sums `ims_quantity_change` (per Jonny's follow-up — `consumable_quantity_change`
over-flagged on live data) rather than the ledger's `supplier_quantity_change`, which *is* in packaging
units but is **NULL for every Pantry receipt** (the largest receiving flow) and so can't be used
universally. `consumable_quantity_change` still drives the breach-date calculation (see the ⚠️ note).

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- DAILY PO over-receipt — TWO-WAY match keyed on ims_sku. For every (po, ims_sku) that RECEIVED
-- yesterday, compare TWO signals:
--   LAYER 1 (PO's own books): PO.received_qty vs PO.ims_sku_qty        (packaging units cs/pk/ea)
--   LAYER 2 (ledger cumulative): SUM(ims_quantity_change) vs PO.consumable_sku_qty  (base oz/lb/g)
-- Flag if EITHER layer is over.
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday
WITH touched AS (   -- (po, ims_sku) received on run_date
  SELECT DISTINCT ref_order_id AS po, ims_sku
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Purchase Order' AND ims_sku IS NOT NULL AND DATE(datetime_utc) = run_date
),

received AS (   -- LAYER 2: cumulative ledger receipts (base units), 30-day lookback
  SELECT
    l.ref_order_id               AS po,
    l.ims_sku,
    SUM(l.ims_quantity_change)   AS led_received,
    ANY_VALUE(l.consumable_uom)  AS received_uom
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` l
  JOIN touched t ON l.ref_order_id = t.po AND l.ims_sku = t.ims_sku
  WHERE l.ref_order_type = 'Purchase Order'
    AND DATE(l.datetime_utc) <= run_date
    AND l.datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(run_date), INTERVAL 30 DAY)
  GROUP BY po, ims_sku
),

ordered AS (   -- ordered in BOTH units + the PO's own received_qty (LAYER 1)
  SELECT
    po,
    ims_sku,
    SUM(ims_sku_qty)          AS ordered_pkg,     -- packaging units — Layer 1
    SUM(consumable_sku_qty)   AS ordered_base,     -- base units      — Layer 2
    SUM(received_qty)         AS po_received,      -- the PO's own cumulative received (packaging)
    ANY_VALUE(consumable_uom) AS ordered_uom,
    ANY_VALUE(ims_uom)        AS ims_uom
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE ims_sku IS NOT NULL AND order_type = 'Purchase'
  GROUP BY po, ims_sku
)

SELECT
  r.po,
  r.ims_sku,
  o.ordered_pkg, o.ims_uom, o.po_received,                            -- Layer 1 (packaging)
  o.ordered_base, o.ordered_uom, r.led_received, r.received_uom,      -- Layer 2 (base)
  (o.po_received  > o.ordered_pkg  * 1.30) AS po_over,
  (r.led_received > o.ordered_base * 1.30) AS led_over,
  (o.ordered_uom != r.received_uom)        AS uom_mismatch
FROM received r
JOIN ordered o USING (po, ims_sku)
WHERE (o.ordered_pkg > 0 OR o.ordered_base > 0)
  AND ( (o.ordered_uom != r.received_uom)                                   -- UoM mismatch
     OR (o.ordered_pkg  > 0 AND o.po_received  > o.ordered_pkg  * 1.30)     -- Layer 1 over
     OR (o.ordered_base > 0 AND r.led_received > o.ordered_base * 1.30) )   -- Layer 2 over
ORDER BY led_over DESC, po_over DESC
```

#### Live finder SQL (what runs daily)

```sql
-- PO over-receipt (TWO-WAY match, keyed on ims_sku): flag if the PO's OWN received_qty vs
-- ims_sku_qty (Layer 1, packaging units) OR the ledger cumulative vs consumable_sku_qty
-- (Layer 2, base units) is over the threshold. Pure UoM-mismatch rows (neither layer over)
-- become PO_UOM_MISMATCH; the rest PO_OVER_RECEIPT (over_frac >= 1.00 -> Urgent, else High).
-- daily batch target = the just-closed day (yesterday PST in prod)
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

WITH t AS (
  SELECT DISTINCT
    ref_order_id AS po,
    ims_sku
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE
    ref_order_type = 'Purchase Order' AND ims_sku IS NOT NULL
    AND DATE(datetime_utc) = run_date
),

evt AS (
  SELECT
    l.ref_order_id AS po,
    l.ims_sku,
    l.consumable_sku,
    l.datetime_utc,
    l.ims_quantity_change AS q,
    l.consumable_uom AS ruom,
    l.facility_name AS facility,
    l.facility_type,
    l.system_of_origin AS system,
    l.item_name,
    l.l1_action,
    l.l2_action,
    SUM(l.consumable_quantity_change) OVER (
      PARTITION BY l.ref_order_id, l.ims_sku ORDER BY l.datetime_utc
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS running_recv,
    -- how many 'Add' receipts share this exact quantity (>=2 = probable double-booking).
    -- Partition key CAST to STRING — BigQuery can't PARTITION BY a FLOAT64.
    SUM(IF(l.l1_action = 'Add' AND l.consumable_quantity_change > 0, 1, 0)) OVER (
      PARTITION BY l.ref_order_id, l.ims_sku, CAST(ROUND(l.consumable_quantity_change, 4) AS STRING)
    ) AS same_qty_receipts
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger` AS l
  INNER JOIN t
    ON l.ref_order_id = t.po AND l.ims_sku = t.ims_sku
  -- ref_order_type='Purchase Order' INTENTIONALLY captures EVERY ledger line tied to the PO,
  -- positive and negative, so SUM(q) below is a true NET. A receiver may double-log / over-log
  -- a receipt and then a correction is booked back against the same PO — either an auto negative
  -- receipt (l1/l2 = Remove/PO Receipt) or a manual fix (Adjust/Update Received Order). Both are
  -- ref_order_type='Purchase Order', so they net out here. Do NOT narrow this to l1_action='Add'
  -- or l2_action LIKE '%Receipt%' — that would drop the manual corrections and re-break netting.
  -- (Corrections booked as generic Adjust/Cycle-Count carry NO PO ref and are deliberately left
  -- alone: they can't be attributed to a specific PO without a fuzzy SKU+facility+window guess.)
  WHERE
    l.ref_order_type = 'Purchase Order' AND l.ims_sku IS NOT NULL
    AND DATE(l.datetime_utc) <= run_date
    AND l.datetime_utc >= TIMESTAMP_SUB(TIMESTAMP(run_date), INTERVAL 30 DAY)
),

received AS (   -- LAYER 2 basis: net ledger receipts per (po, ims_sku), BASE units
  SELECT
    po,
    ims_sku,
    SUM(q) AS led_received,
    ANY_VALUE(ruom) AS received_uom,
    ANY_VALUE(consumable_sku) AS consumable_sku,
    ANY_VALUE(facility) AS facility,
    ANY_VALUE(facility_type) AS facility_type,
    ANY_VALUE(system) AS system,
    ANY_VALUE(item_name) AS item_name,
    -- movement action of the largest receipt = the dominant receiving event (l1 / l2)
    ANY_VALUE(l1_action HAVING MAX q) AS move_l1,
    ANY_VALUE(l2_action HAVING MAX q) AS move_l2,
    MAX(same_qty_receipts) AS dup_receipts   -- >=2 = ledger booked the same receipt twice
  FROM evt
  GROUP BY po, ims_sku
),

ordered AS (   -- ordered in BOTH units + the PO's OWN received_qty (LAYER 1), per (po, ims_sku)
  SELECT
    po,
    ims_sku,
    SUM(ims_sku_qty) AS ordered_pkg,    -- packaging units (cs/pk/ea) — Layer 1 basis
    SUM(consumable_sku_qty) AS ordered_base,    -- base units (oz/lb/g)       — Layer 2 basis
    SUM(received_qty) AS po_received,     -- the PO's own cumulative received (packaging)
    ANY_VALUE(consumable_uom) AS ordered_uom,
    ANY_VALUE(ims_uom) AS ims_uom,
    ANY_VALUE(supplier_name) AS supplier,
    ANY_VALUE(status) AS status
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE ims_sku IS NOT NULL AND order_type = 'Purchase'   -- PO-side: purchases only (for now)
  GROUP BY po, ims_sku
),

breach AS (
  SELECT
    e.po,
    e.ims_sku,
    -- first receipt where the ledger cumulative (base) crossed the over-receipt threshold
    DATE(MIN(IF(e.running_recv > o.ordered_base * (1 + 0.3), e.datetime_utc, NULL))) AS over_breach_date,
    -- first receipt that introduced a unit different from the order's
    DATE(MIN(IF(
      o.ordered_uom IS NOT NULL AND e.ruom IS NOT NULL AND e.ruom != o.ordered_uom,
      e.datetime_utc, NULL
    ))) AS uom_breach_date,
    DATE(MIN(e.datetime_utc)) AS first_receipt_date,
    DATE(MAX(e.datetime_utc)) AS last_receipt_date
  FROM evt AS e INNER JOIN ordered AS o ON e.po = o.po AND e.ims_sku = o.ims_sku
  GROUP BY po, ims_sku
),

flagged AS (   -- TWO-WAY match: keep a row if the PO's own books OR the ledger cumulative are over
  SELECT
    r.po,
    r.ims_sku,
    r.consumable_sku,
    r.item_name,
    o.ordered_pkg,
    o.ordered_base,
    o.po_received,
    r.led_received,
    o.ordered_uom,
    r.received_uom,
    o.ims_uom,
    r.facility,
    r.facility_type,
    r.system,
    o.supplier,
    o.status,
    r.move_l1,
    r.move_l2,
    r.dup_receipts,
    b.over_breach_date,
    b.uom_breach_date,
    b.first_receipt_date,
    b.last_receipt_date,
    (o.ordered_pkg > 0 AND o.po_received > o.ordered_pkg * (1 + 0.3)) AS po_over,
    (o.ordered_base > 0 AND r.led_received > o.ordered_base * (1 + 0.3)) AS led_over,
    SAFE_DIVIDE(o.po_received, NULLIF(o.ordered_pkg, 0)) - 1 AS po_over_frac,
    SAFE_DIVIDE(r.led_received, NULLIF(o.ordered_base, 0)) - 1 AS led_over_frac,
    GREATEST(
      COALESCE(SAFE_DIVIDE(o.po_received, NULLIF(o.ordered_pkg, 0)) - 1, -9),
      COALESCE(SAFE_DIVIDE(r.led_received, NULLIF(o.ordered_base, 0)) - 1, -9)
    ) AS over_frac,
    (o.ordered_uom IS NOT NULL AND r.received_uom IS NOT NULL AND o.ordered_uom != r.received_uom) AS uom_mismatch
  FROM received AS r INNER JOIN ordered AS o ON r.po = o.po AND r.ims_sku = o.ims_sku
  INNER JOIN breach AS b ON r.po = b.po AND r.ims_sku = b.ims_sku
  WHERE (o.ordered_pkg > 0 OR o.ordered_base > 0) AND (
    (o.ordered_uom IS NOT NULL AND r.received_uom IS NOT NULL AND o.ordered_uom != r.received_uom)
    OR (o.ordered_pkg > 0 AND o.po_received > o.ordered_pkg * (1 + 0.3))
    OR (o.ordered_base > 0 AND r.led_received > o.ordered_base * (1 + 0.3))
  )
),

ranked AS (
  SELECT
    *,
    COUNT(*) OVER () AS total_matches,
    ROW_NUMBER() OVER (
      PARTITION BY (CASE
        WHEN uom_mismatch AND NOT (po_over OR led_over) THEN 'uom'
        WHEN over_frac >= 1.0 THEN 'over_urgent'  -- >=100% over (>=2x ordered): likely error (Urgent)
        ELSE 'over_high'
      END)                         -- 30-99% over: supply-chain signal (High)
      ORDER BY over_frac DESC
    ) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn) FROM ranked
WHERE rn <= 500
ORDER BY over_frac DESC
```

### Plain-English walkthrough

This is the most involved rule, because "did we receive too much?" is now asked **two ways at once**,
each in its own unit. The live query builds the answer in named steps (`WITH <name> AS ( … )`); read
it as a short pipeline. Both SQL blocks do the same job; the catalog version is the simpler
documented form, and the **live version's thresholds are the ones actually in force** (30% / 100%).

1. **`run_date` = yesterday** — the day we're checking.

2. **`evt` — pull the receipt history for the (PO, IMS SKU) pairs that moved yesterday.** First it
   finds every `(po, ims_sku)` that *received something yesterday* (the small `JOIN (… DATE(datetime_utc)
   = run_date …)` sub-query) — we only re-examine orders that actually had activity, which keeps the
   query cheap. For each, it pulls **every** ledger line tied to that PO+IMS-SKU over the last **30
   days** and adds a **running cumulative total** (`running_recv`, off `consumable_quantity_change`) in
   **base units** — row by row in time order, "how much have we received against this PO+item *so
   far*." This running total only feeds the **breach date** below; it isn't the column the flag decision
   runs on (see step 3). Why include positive **and** negative lines? Because if a receiver over-logs a
   receipt and a correction is later booked back against the same PO, the two cancel out — so the
   running total is a **true net**, and we don't flag a mistake that was already fixed.

3. **`received` — Layer 2's bottom line.** Collapses `evt` to one row per `(po, ims_sku)` with the
   **net ledger received quantity** — `SUM(q)`, where `q` is `ims_quantity_change` (base units, see the
   ⚠️ note above for why this column and not `consumable_quantity_change`) — and its unit, plus triage
   details (facility, system, the dominant receiving action).

4. **`ordered` — what the PO called for, in *both* units, plus its own count.** From the **PO Table**,
   per `(po, ims_sku)`: `ordered_pkg` (= `SUM(ims_sku_qty)`, packaging), `ordered_base`
   (= `SUM(consumable_sku_qty)`, base), and **`po_received`** (= `SUM(received_qty)`, the PO's own
   running received count in packaging units — this is **Layer 1**), plus supplier and status.

5. **`breach` — when the problem started.** For each pair it finds the **first** receipt at which the
   ledger running total crossed the over-receipt line, and the first receipt that introduced a wrong
   unit. This gives the exception an accurate "as of" date instead of just "today."

6. **`flagged` — apply the two-way test.** Joins received ↔ ordered ↔ breach and computes both layers:
   - **`po_over`** = `po_received > ordered_pkg × 1.30` (the PO's own books, packaging units).
   - **`led_over`** = `led_received > ordered_base × 1.30` (the ledger cumulative, base units).
   A row is kept if **either** layer is over, *or* the received unit doesn't match the ordered unit.
   `over_frac` is the **worse** of the two layers' overage fractions and decides the severity band.

7. **`ranked` + final line — fair capping.** Rows are numbered *within each band* (pure UoM mismatch /
   30–99% over / ≥100% over) so the **500-row daily cap** keeps all populations represented rather than
   letting the most extreme rows crowd out the rest. The final line drops the helper number and sorts
   worst-first.

**What the ticket tells you.** Each exception records a plain-English **`match`** verdict — one of:
*"Confirmed by both the PO's own receipts and the ledger cumulative"*; *"PO receipt appears correct
(matched the order); the ledger over-counted — likely a duplicate or erroneous ledger entry.
Investigate the ledger, not the receiving"*; or *"The PO's own received_qty is over-ordered; the
ledger cumulative is within range"* — plus a cross-check line showing the other layer's numbers.

**Ledger-only case (Check 1 clean, Check 2 over).** When the PO's own receipt count matches the order
but the ledger cumulative is over, the receiving was almost certainly right and the **ledger** is the
one that's wrong. Those tickets get the "investigate the ledger" verdict above and a machine flag
(`likely_ledger_error`) so the dashboard can group them (routing is unchanged — still Field Ops). The
live query also computes `same_qty_receipts` / `dup_receipts` — a count of identical `'Add'` receipts
booked against the same PO+item — and when it's **≥ 2** the verdict appends *"N identical receipts
detected (probable double-booking)"*, the classic signature of the same receipt logged twice.

**How the join works & why it's needed:** the ledger and the PO table are stitched together on
**`ledger.ref_order_id = PO.po`** (same purchase order) **and** **`ledger.ims_sku = PO.ims_sku`**
(same item, by the *raw* system id) — see the `USING (po, ims_sku)` joins. Without the join we'd only
know what we *received*; we need the PO table to know what was *ordered* — and its own receipt count —
so we can run both layers of the match.

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** PO Table (`int_ledger_purchase_orders`).
**Join keys:** `ref_order_id` ⇄ `po` (the purchase order) and **`ims_sku` ⇄ `ims_sku`** (the item, by raw system id).

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `ims_sku` (both) | The raw item id the source systems stamp on both tables. | **Join key & grain** — the item link, replacing the translated `consumable_sku`. |
| `ref_order_id` (ledger) | The PO a receipt belongs to. | **Join key** to the PO table; identifies the order. |
| `ims_quantity_change` (ledger) | How much the item moved on that line, in **base units** (+ in, − out). | **Summed** into the Layer-2 net received quantity (`led_received`) — decides `led_over`. |
| `consumable_quantity_change` (ledger) | Same movement, in base units, from a different source column. | Drives the `running_recv` cumulative used **only** for the breach date — not the flag decision (see ⚠️ note above). |
| `consumable_uom` (ledger) | The base unit the receipt was booked in. | Compared to the PO's base unit (UoM-mismatch check). |
| `datetime_utc` (ledger) | When the movement happened. | Picks "touched yesterday", the 30-day window, and the breach date. |
| `received_qty` (PO) | The PO's **own** running received count, in **packaging units**. | **Layer 1 numerator** — the "PO receipt" signal. |
| `ims_sku_qty` (PO) | Quantity ordered, in **packaging units** (= `supplier_sku_qty`). | **Layer 1 benchmark** — `received_qty` is compared against this. |
| `consumable_sku_qty` (PO) | Quantity ordered, in **base units**. | **Layer 2 benchmark** — the ledger cumulative is compared against this. |
| `ims_uom` / `consumable_uom` (PO) | Packaging unit / base unit the item was ordered in. | Displayed on the ticket; base unit drives the UoM-mismatch check. |
| `supplier_name`, `status` (PO) | Vendor and PO status. | Triage context on the ticket. |
| `facility_name` / `facility_type` (ledger) | Where it was received. | Triage + routing (HDR vs CK/Production). |

### Examples of flagged records (from live data)

**Both layers agree — a clear over-receipt.** `VDC 4312` / IMS `4200136-2` (*Pico de Gallo Salsa*,
Shiphero): ordered **1**, but the PO's own books show **334 received** and the ledger cumulative shows
**302,604 g against 906 g ordered** — both far past the ≥100% line, so **Urgent**. Verdict: *"Confirmed
by both the PO's own receipts and the ledger cumulative."*

**Ledger-only — the two-way match earning its keep.** `PO 61920` / IMS `8807623` (*Pizza, Cheese, 10"*,
Roncadin):

| Field | Value |
|---|---|
| `po` / `ims_sku` | `PO 61920` / `8807623` |
| Layer 1 (PO's own books) | received **1,620** of **1,620** ordered — **within range** ✅ |
| Layer 2 (ledger cumulative) | received **27,540 ea** of **1,620 ea** ordered → **+1,600% over** ❌ |
| `match` | *Ledger cumulative over-received; the PO's own received_qty is still within range (possible reconciliation gap).* |

**Why it matters:** the PO's own receipt count looks perfectly clean (1,620 of 1,620), so the *old*
single-signal rule would have **missed** it. The ledger, however, booked **17× the quantity** the PO
acknowledges — a genuine reconciliation gap between the warehouse ledger and the buying system that is
exactly what the second layer exists to surface.

---

## PO-06 · Missing Unit Conversion (Consumable ↔ Vendor SKU)

> **In one sentence:** find an item we're **buying** for which the product catalog has **no way to
> convert the vendor's unit** (e.g. a *case*) into **the unit we actually use** (e.g. *each* or
> *grams*) — either the item isn't in the catalog at all, or the vendor we bought it from isn't
> linked to it — so a receipt can't be turned into the right on-hand quantity.

### At a glance

| | |
|---|---|
| **Rule number** | PO-06 |
| **Rule type** | `REFERENTIAL` (a "this must resolve against a reference table" check) |
| **Severity** | **Urgent** — same-day SLA |
| **Owner / routed team** | Procurement |
| **Default assignee** | Tom Becker |
| **Jira** | Project **WIQ** · Component **UoM / Conversions** |
| **Source tables** | PO Table (`int_ledger_purchase_orders`) **⋈** Supply-chain product catalog (`supply_chain_catalog.wonder_products`) |
| **Jonny Signoff** | 2026-07-15 |
| **Grain** | **One ticket per (Consumable SKU, Vendor SKU)** — the vendor-item that can't be converted, not per PO line. |
| **Key settings** | `po_missing_uom_conversion_lookback_days` = **30** (backfill window; daily flags items purchased that day) |
| **Live status** | 🟢 **Live — runs daily.** Over a 30-day backfill it finds **134** unconvertible (consumable, vendor) pairs; the daily run flags the ones purchased that day. |

### The new table: the supply-chain product catalog

This is the first rule to read `wonder-dw-prod-brd.**supply_chain_catalog.wonder_products**` — a
**view** (~765 rows / ~534 products) that is the master **unit-of-measure / packaging catalog** for
**Wonder-family products**. Each row is one *(product × packaging level)* and carries the conversion
factors (`level_1..4_conversion_factor`, `cumulative_conversion_factor`, `base_uom` /
`base_uom_quantity`) that translate a vendor pack → the consumable base unit, plus three SKU
identities that let us tie the PO's SKUs to it:

| Catalog column | Is the… | Ties to PO column |
|---|---|---|
| `hdr_product_sku` (e.g. `4000315`) | Consumable / HDR SKU | **`consumable_sku`** ✅ the join key |
| `vendor_product_skus[]` / `priority_vendor_product_sku` | Vendor SKU(s) | **`supplier_sku`** ✅ the link check |
| `wonder_product_sku` (e.g. `W4200042`) | internal Wonder SKU | *(not `wonder_sku` — different ID namespace, not used)* |

**Important:** the catalog's conversion factors are **100% populated** (there are *no* rows with a
null/zero factor). So "missing unit conversion" is **not** a blank-field problem inside the catalog —
it is a **coverage / linkage gap**: an item is being *purchased* but the catalog can't resolve its
*(Consumable SKU, Vendor SKU)* to a conversion at all. That happens two ways, both flagged:
1. **No catalog record** — the consumable has no row in `wonder_products`.
2. **Vendor not linked** — the consumable *is* in the catalog, but the PO's vendor SKU isn't among
   that product's linked vendor SKUs, so we don't know which packaging conversion applies to it.

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Framework PO-06: a purchased Wonder-family item whose Consumable SKU <> Vendor SKU can't be
-- resolved to a unit conversion in the supply-chain catalog (no record, or vendor SKU not linked).
WITH cat AS (
  SELECT
    hdr_product_sku AS hdr,
    ARRAY_CONCAT_AGG(vendor_product_skus) AS vendors,
    ARRAY_AGG(DISTINCT priority_vendor_product_sku IGNORE NULLS) AS pvendors
  FROM `wonder-dw-prod-brd.supply_chain_catalog.wonder_products`
  WHERE status = 'ACTIVE'
    AND hdr_product_sku IS NOT NULL
  GROUP BY hdr_product_sku
)

SELECT
  p.consumable_sku,
  p.supplier_sku,
  p.supplier_name,
  p.consumable_uom,
  p.supplier_uom
FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders` p
LEFT JOIN cat c ON p.consumable_sku = c.hdr
WHERE p.order_type = 'Purchase'
  AND p.consumable_sku IS NOT NULL
  AND p.supplier_sku IS NOT NULL
  AND (p.ims_sku_type IN ('WSKU','Pack SKU') OR REGEXP_CONTAINS(p.consumable_sku, r'^40[0-9]{5}$'))
  AND NOT REGEXP_CONTAINS(p.consumable_sku, r'^9[0-9]{6}$')   -- exclude smallwares/packaging
  AND p.consumable_uom != p.supplier_uom
  AND (c.hdr IS NULL OR NOT (p.supplier_sku IN UNNEST(c.vendors) OR p.supplier_sku IN UNNEST(c.pvendors)))
```

#### Live finder SQL (what runs daily)

```sql
-- Purchased Wonder-family item whose Consumable SKU <> Vendor SKU has no unit conversion in the
-- catalog (framework PO-06). One row per (consumable_sku, supplier_sku). Daily flags items
-- purchased on the run-date; backfill sweeps the lookback window.
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH cat AS (   -- one row per Wonder product; join key hdr_product_sku = PO consumable_sku
  SELECT
    hdr_product_sku AS hdr,
    ARRAY_CONCAT_AGG(vendor_product_skus) AS vendors,          -- all linked vendor SKUs
    ARRAY_AGG(DISTINCT priority_vendor_product_sku IGNORE NULLS) AS pvendors,
    ANY_VALUE(wonder_product_name) AS product_name
  FROM `wonder-dw-prod-brd.supply_chain_catalog.wonder_products`
  WHERE status = 'ACTIVE'
    AND hdr_product_sku IS NOT NULL
  GROUP BY hdr_product_sku
),

po AS (   -- Wonder-family purchase lines in scope, collapsed to one row per (consumable, vendor)
  SELECT
    consumable_sku,
    supplier_sku,
    ANY_VALUE(consumable_uom)   AS consumable_uom,
    ANY_VALUE(supplier_uom)     AS supplier_uom,
    ANY_VALUE(supplier_name)    AS supplier_name,
    ANY_VALUE(destination_name) AS facility,
    ANY_VALUE(po_source_system) AS system,
    ANY_VALUE(ims_sku_type)     AS sku_type,
    ANY_VALUE(wonder_sku)       AS wonder_sku,
    ANY_VALUE(po)               AS sample_po,
    COUNT(DISTINCT po)          AS po_count,
    MIN(po_date_utc)            AS first_po_date,
    MAX(po_date_utc)            AS last_po_date
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase'
    AND consumable_sku IS NOT NULL
    AND supplier_sku IS NOT NULL
    AND (ims_sku_type IN ('WSKU','Pack SKU') OR REGEXP_CONTAINS(consumable_sku, r'^40[0-9]{5}$'))
    AND NOT REGEXP_CONTAINS(consumable_sku, r'^9[0-9]{6}$')  -- exclude 9xxxxxx smallwares/packaging (never in the food catalog)
    AND consumable_uom != supplier_uom            -- a conversion is genuinely required
    AND DATE(po_date_utc) = run_date
  GROUP BY consumable_sku, supplier_sku
),

flagged AS (
  SELECT
    p.*,
    c.product_name,
    (c.hdr IS NULL) AS missing_record
  FROM po p
  LEFT JOIN cat c ON p.consumable_sku = c.hdr
  WHERE c.hdr IS NULL                                                     -- no catalog record at all
     OR NOT (p.supplier_sku IN UNNEST(c.vendors)                         -- or vendor SKU not linked
             OR p.supplier_sku IN UNNEST(c.pvendors))
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                           AS total_matches,
    ROW_NUMBER() OVER (ORDER BY last_po_date DESC) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY last_po_date DESC
```

### Plain-English walkthrough

The rule stitches the **PO Table** (what we bought, from whom, in what unit) to the **product
catalog** (the master unit conversions) and keeps the purchases the catalog can't resolve.

1. **`run_date` = yesterday** — the day we're checking (the daily job always checks the last fully-closed day).

2. **`cat` — boil the catalog down to one row per product.** Group the catalog by `hdr_product_sku`
   (the consumable/HDR SKU) and collect, for each product, **all** of its linked vendor SKUs (the
   `vendor_product_skus` arrays concatenated, plus the `priority_vendor_product_sku`). This is the
   reference list: *"for this consumable, here are the vendor SKUs we know how to convert."*

3. **`po` — the purchases worth checking, de-duplicated.** From the PO Table keep only:
   - `order_type = 'Purchase'` — actual purchases.
   - **Wonder-family items only** — `ims_sku_type` is `WSKU` or `Pack SKU`, *or* the consumable SKU is
     in the `40xxxxx` family. This deliberately **excludes raw vendor goods** that were never meant to
     have a Wonder conversion, so the rule doesn't flag the entire purchasing universe. It also
     **excludes the `9xxxxxx` smallwares/packaging family** (cups, containers, box liners from Uline /
     Ed Don) — those are operational supplies that never live in the food product catalog, so flagging
     them would only create permanent, un-closeable tickets.
   - `consumable_uom != supplier_uom` — **a conversion is only *needed* when the units differ** (bought
     by the case, used by the each/gram). If the units already match, there's nothing to convert.
   - Then collapse to **one row per (consumable_sku, supplier_sku)** so the same vendor-item isn't
     re-flagged for every PO line, keeping a sample PO and count for triage.

4. **`flagged` — apply the test.** `LEFT JOIN` each purchase to the catalog on
   **`consumable_sku = hdr_product_sku`** and keep it only if **either**: there's **no catalog row**
   (`c.hdr IS NULL`), **or** there is one but the **PO's vendor SKU isn't in that product's linked
   vendor SKUs**. Both mean the same thing operationally — we can't convert this vendor's pack into the
   consumable unit. `missing_record` records which of the two it was, for the ticket.

5. **`ranked` + final line — cap.** Stamp the total match count on every row, order most-recently-
   purchased first, keep the first 500, drop the helper column.

**How the join works & why it's needed:** the two tables meet on **`PO.consumable_sku =
catalog.hdr_product_sku`** (the same item) and then the **vendor** side is checked with
`supplier_sku IN UNNEST(vendor_product_skus)` (is this vendor linked?). We need *both* tables because
the PO knows *what we bought and from whom* but not *how to convert it*; the catalog knows the
conversion but only for the SKUs it has on file. (Note: `PO.wonder_sku` is an `8xxxxxx`-series number
in a **different ID namespace** than the catalog's `W42xxxxx` `wonder_product_sku`, so it is *not* a
valid join key and isn't used.)

**Auto-close:** each day the rule re-checks every open PO-06 ticket and closes it once the catalog
resolves that pair — a record now exists **and** the vendor SKU is linked.

### Tables & columns used

**Tables:** PO Table (`int_ledger_purchase_orders`) **⋈** Product catalog (`supply_chain_catalog.wonder_products`).
**Join keys:** `consumable_sku` ⇄ `hdr_product_sku` (the item); `supplier_sku` ∈ `vendor_product_skus` / `priority_vendor_product_sku` (the vendor link).

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `consumable_sku` (PO) | The consumable/HDR item number. | **Join key** to the catalog; part of the ticket identity. |
| `supplier_sku` (PO) | The vendor's item number we bought. | **The link check** — must be a linked vendor SKU for this product. |
| `consumable_uom` / `supplier_uom` (PO) | The consumable unit vs the vendor's unit. | **Scope** — only checked when they differ (a conversion is needed). |
| `ims_sku_type` (PO) | Whether the line is a WSKU / Pack SKU / Vendor SKU. | **Scope** — limits the rule to Wonder-family items. |
| `order_type` (PO) | Purchase vs Transfer. | **Filter** — purchases only. |
| `po_date_utc` (PO) | The PO's date. | **Filter** — yesterday (daily) / lookback window (backfill); age anchor. |
| `hdr_product_sku` (catalog) | The product's consumable/HDR SKU. | **Join key** — matched to `consumable_sku`. |
| `vendor_product_skus[]`, `priority_vendor_product_sku` (catalog) | The vendor SKUs linked to the product. | **The reference** — the set the PO's `supplier_sku` must be in. |
| `cumulative_conversion_factor`, `base_uom` (catalog) | The actual unit conversion. | The value that becomes unusable when the linkage is missing. |
| `wonder_product_name` (catalog) | Human-readable product name. | Triage — shown when the item is in the catalog. |

### Example of a flagged record (from live data)

A pair caught by the 30-day backfill, routed to Procurement:

| Field | Value |
|---|---|
| `consumable_sku` / `item_name` | `4001221F` / `Chicken Sandwich Filet FZN (15 ea)` |
| `supplier_sku` | `1142589-EA` |
| `supplier_name` | `US Foods Inc` |
| `consumable_uom` ← `supplier_uom` | `ea` ← `cs` (bought by the case, used by the each) |
| `gap` | **Vendor SKU not linked to this consumable in the catalog** |

**Why it's flagged:** the product *is* in the catalog, but the vendor SKU we actually bought
(`1142589-EA`, US Foods) isn't linked to it — so there's no conversion telling us how many *eaches* a
*case* of `1142589-EA` yields. Every receipt against it lands in the wrong on-hand quantity until
Procurement links the vendor SKU (or adds the catalog record), hence the **Urgent** severity.

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
| **Jonny Signoff** | 2026-07-15 |
| **Grain** | **One ticket per PO** (not per line). |
| **Key settings** | `po_no_receipt_overdue_days` = **2** (grace days past expected) · `po_no_receipt_overdue_lookback_days` = **7** (only recently-overdue POs; 0 = full backlog) |
| **Live status** | 🟢 **Live — runs daily.** With the 7-day window it flagged **2** POs on the 2026-07-06 run (`KAN-1041`, `KAN-1042`). |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Framework PO-07: an OPEN Purchase PO past expected_date + N days with nothing received and
-- not cancelled. Aggregated to PO grain — a PO is 'nothing received' only when NO line has any
-- received_qty. N = po_no_receipt_overdue_days (default 2).
SELECT
  po,
  ANY_VALUE(destination_name)    AS facility,
  ANY_VALUE(supplier_name)       AS supplier_name,
  MAX(expected_date)             AS expected_date,
  SUM(COALESCE(received_qty, 0)) AS total_received
FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
WHERE order_type = 'Purchase'
  AND UPPER(status) = 'OPEN'
GROUP BY po
HAVING total_received = 0
   AND MAX(expected_date) < DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
```

#### Live finder SQL (what runs daily)

```sql
-- Open Purchase PO past expected_date + 2 days with nothing received and not cancelled
-- (framework PO-07), limited to the last 7 days. One row per PO.
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH po_agg AS (
  SELECT
    po,
    ANY_VALUE(destination_name)    AS facility,
    ANY_VALUE(supplier_name)       AS supplier_name,
    ANY_VALUE(po_source_system)    AS system,
    SUM(COALESCE(received_qty, 0)) AS total_received,          -- across ALL lines of the PO
    LOGICAL_OR(UPPER(status) = 'OPEN') AS has_open_line,       -- still awaiting receipt somewhere
    STRING_AGG(DISTINCT status, ', ') AS po_status,
    COUNT(*)                       AS line_count,
    MAX(IF(UPPER(status) = 'OPEN', expected_date, NULL)) AS expected_date,
    SUM(IF(UPPER(status) = 'OPEN', COALESCE(consumable_sku_qty, 0), 0)) AS total_ordered,
    COUNTIF(UPPER(status) = 'OPEN') AS open_line_count
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase'
    AND po IS NOT NULL
    AND TRIM(po) <> ''
  GROUP BY po
),

flagged AS (
  SELECT
    *,
    DATE_ADD(expected_date, INTERVAL 2 DAY) AS breach_date,
    DATE_DIFF(run_date, expected_date, DAY) AS days_overdue
  FROM po_agg
  WHERE total_received = 0              -- nothing received on the whole PO
    AND has_open_line                  -- still open / not cancelled or closed out
    AND expected_date IS NOT NULL
    AND expected_date < DATE_SUB(run_date, INTERVAL 2 DAY)
    AND expected_date >= DATE_SUB(run_date, INTERVAL 7 DAY)   -- recency window
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                           AS total_matches,
    ROW_NUMBER() OVER (ORDER BY expected_date ASC) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY expected_date ASC
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
| **Jonny Signoff** | 2026-07-15 |
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
SELECT
  po,
  ANY_VALUE(destination_name)        AS facility,
  ANY_VALUE(supplier_name)           AS supplier_name,
  MAX(expected_date)                 AS expected_date,
  SUM(COALESCE(received_qty, 0))     AS total_received,
  SUM(COALESCE(supplier_sku_qty, 0)) AS total_ordered
FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
WHERE order_type = 'Purchase'
  AND UPPER(status) NOT IN ('CLOSED','COMPLETED','CANCELLED','CANCELED','VOIDED')
GROUP BY po
HAVING total_received > 0
   AND total_received < total_ordered
   AND MAX(expected_date) < DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
```

#### Live finder SQL (what runs daily)

```sql
-- Under-received Purchase PO (received>0 but < ordered) still not closed 3 days past
-- expected_date (framework PO-08), limited to the last 7 days. One row per PO.
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH po_agg AS (
  SELECT
    po,
    ANY_VALUE(destination_name)        AS facility,
    ANY_VALUE(supplier_name)           AS supplier_name,
    ANY_VALUE(po_source_system)        AS system,
    SUM(COALESCE(received_qty, 0))     AS total_received,   -- supplier units, across ALL lines
    SUM(COALESCE(supplier_sku_qty, 0)) AS total_ordered,    -- supplier units, across ALL lines
    LOGICAL_OR(UPPER(status) NOT IN ('CLOSED','COMPLETED','CANCELLED','CANCELED','VOIDED')) AS not_closed,
    STRING_AGG(DISTINCT status, ', ')  AS po_status,
    COUNT(*)                           AS line_count,
    MAX(IF(UPPER(status) NOT IN ('CLOSED','COMPLETED','CANCELLED','CANCELED','VOIDED'), expected_date, NULL)) AS expected_date,
    COUNTIF(UPPER(status) NOT IN ('CLOSED','COMPLETED','CANCELLED','CANCELED','VOIDED')) AS open_line_count
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase'
    AND po IS NOT NULL
    AND TRIM(po) <> ''
  GROUP BY po
),

flagged AS (
  SELECT
    *,
    total_ordered - total_received          AS shortfall_qty,
    DATE_ADD(expected_date, INTERVAL 3 DAY) AS breach_date,
    DATE_DIFF(run_date, expected_date, DAY) AS days_overdue
  FROM po_agg
  WHERE total_received > 0                       -- received something
    AND total_received < total_ordered - 0.001   -- but under-received (short by even 1)
    AND not_closed                               -- not closed by Supply Chain
    AND expected_date IS NOT NULL
    AND expected_date < DATE_SUB(run_date, INTERVAL 3 DAY)
    AND expected_date >= DATE_SUB(run_date, INTERVAL 7 DAY)   -- recency window
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                           AS total_matches,
    ROW_NUMBER() OVER (ORDER BY expected_date ASC) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY expected_date ASC
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
| **Jonny Signoff** | 2026-07-15 |
| **Live status** | 🟢 **Live — runs daily.** Flagged **0** on yesterday's data; it fires whenever a closed PO line dated that day is missing its vendor price. |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Purchase PO lines with no usable vendor (supplier) price — receipts can't be costed.
SELECT
  po,
  supplier_sku,
  consumable_sku,
  supplier_name,
  status,
  supplier_price,
  po_date_utc
FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
WHERE order_type = 'Purchase'
  AND (supplier_price IS NULL OR supplier_price = 0)
```

#### Live finder SQL (what runs daily)

```sql
-- CLOSED Purchase PO lines with a $0/NULL vendor price (can't be costed).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH flagged AS (
  SELECT
    po,
    supplier_sku,
    ANY_VALUE(po_source_system)  AS system,
    ANY_VALUE(destination_name)  AS facility,
    ANY_VALUE(supplier_name)     AS supplier_name,
    ANY_VALUE(supplier_sku_name) AS supplier_sku_name,
    ANY_VALUE(status)            AS status,
    MIN(supplier_price)          AS supplier_price,
    MIN(po_date_utc)             AS po_date_utc
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase'
    AND (supplier_price IS NULL OR supplier_price = 0)
    AND supplier_sku IS NOT NULL
    AND UPPER(status) = 'CLOSED'
    AND DATE(po_date_utc) = run_date
  GROUP BY po, supplier_sku
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                          AS total_matches,
    ROW_NUMBER() OVER (ORDER BY po_date_utc DESC) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY po_date_utc DESC
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
| **Jonny Signoff** | 2026-07-15 |
| **Grain** | **One ticket per ledger row** (each correction event). |
| **Key setting** | `po_correction_missing_ref_lookback_days` = **7** (only scan the last 7 days of ledger events; keeps the initial run small) |
| **Live status** | 🟢 **Live — runs daily.** Flagged **29** correction rows on the 2026-07-06 run (`KAN-1044`–`KAN-1072`). |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Framework PO-11: a ledger 'Correction' transaction (l1_action LIKE '%correct%') with a
-- NULL/blank correction_ref_id — the correcting entry doesn't reference what it fixes.
SELECT
  id,
  datetime_utc,
  facility_name,
  system_of_origin,
  l1_action,
  l2_action,
  consumable_sku,
  item_name,
  correction_ref_id
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
  SELECT
    CAST(id AS STRING)          AS id,
    ANY_VALUE(facility_name)    AS facility,
    ANY_VALUE(facility_type)    AS facility_type,
    ANY_VALUE(system_of_origin) AS system,
    ANY_VALUE(consumable_sku)   AS consumable_sku,
    ANY_VALUE(item_name)        AS item_name,
    ANY_VALUE(l1_action)        AS l1_action,
    ANY_VALUE(l2_action)        AS l2_action,
    ANY_VALUE(ref_order_type)   AS ref_order_type,
    ANY_VALUE(ref_order_id)     AS ref_order_id,
    MIN(datetime_utc)           AS datetime_utc
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE LOWER(l1_action) LIKE '%correct%'
    AND (correction_ref_id IS NULL OR TRIM(correction_ref_id) = '')
    AND DATE(datetime_utc) <= run_date
    AND DATE(datetime_utc) > DATE_SUB(run_date, INTERVAL 7 DAY)   -- last 7 days incl. run_date
  GROUP BY id
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                           AS total_matches,
    ROW_NUMBER() OVER (ORDER BY datetime_utc DESC) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY datetime_utc DESC
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
| **Jonny Signoff** | 2026-07-15 |
| **Live status** | 🟢 **Live — safety-net.** Finds **0** on current data (every master PO row has a number); kept switched on so it catches the problem immediately if upstream ever degrades. PO-13 is the **PO-table twin of PO-01** (which checks the *ledger* side). |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Master PO table integrity: a Purchase row with no PO number (safety-net; 0 on current data).
SELECT
  _id,
  supplier_name,
  supplier_sku,
  consumable_sku,
  po_date_utc
FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
WHERE order_type = 'Purchase'
  AND (po IS NULL OR TRIM(po) = '')
```

#### Live finder SQL (what runs daily)

```sql
-- Purchase rows in the PO master with a NULL/blank PO number (safety-net).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH flagged AS (
  SELECT
    CAST(_id AS STRING)       AS id,
    ANY_VALUE(supplier_name)  AS supplier_name,
    ANY_VALUE(supplier_sku)   AS supplier_sku,
    ANY_VALUE(consumable_sku) AS consumable_sku,
    MIN(po_date_utc)          AS po_date_utc
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase'
    AND (po IS NULL OR TRIM(po) = '')
    AND DATE(po_date_utc) = run_date
  GROUP BY id
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                          AS total_matches,
    ROW_NUMBER() OVER (ORDER BY po_date_utc DESC) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
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

> **In one sentence:** find items received yesterday against a **real** purchase order where the PO
> **orders none of that item** — either it isn't on the PO's lines at all, or it's on a line ordered
> for **zero** — a three-way-match break (wrong item, undocumented substitution, a line never set up,
> or a Ship Hero zero-order receive-line we might never invoice the vendor for).

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
| **Jonny Signoff** | 2026-07-15 |
| **Live status** | 🟢 **Live — runs daily.** Fires whenever a SKU is received against a PO that orders none of it (not on the PO, or on a zero-order line). The zero-order-line case is a safety-net per Jonny Li: **0 such lines exist in the PO master today** (checked over 90 days, all source systems), so it adds no tickets right now, but catches the Ship Hero zero-order receive-line the moment one syncs in. (Live version of framework catalog rule PO-02.) |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- 3-way match: a consumable_sku received against an existing PO (order_type='Purchase')
-- that the PO orders NONE of — not on its lines, OR on a line ordered for 0.
WITH led AS (
  SELECT DISTINCT
    ref_order_id AS po,
    consumable_sku
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Purchase Order'
    AND consumable_sku IS NOT NULL
),

po_lines AS (
  SELECT
    po,
    consumable_sku,
    SUM(consumable_sku_qty) AS ordered_qty
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase'
    AND consumable_sku IS NOT NULL
  GROUP BY po, consumable_sku
),

po_exists AS (
  SELECT DISTINCT po
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase'
)

SELECT l.po, l.consumable_sku
FROM led l
JOIN po_exists pe USING (po)
LEFT JOIN po_lines pl
  ON l.po = pl.po AND l.consumable_sku = pl.consumable_sku
WHERE COALESCE(pl.ordered_qty, 0) <= 0  -- PO exists, but orders none of this received SKU
```

#### Live finder SQL (what runs daily)

```sql
-- 3-way match: a consumable_sku received against an existing PO that orders none of it
-- (not on its lines, OR on a line ordered for 0 — a Ship Hero zero-order receive-line).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH led AS (   -- items received against POs yesterday
  SELECT
    ref_order_id                                        AS po,
    consumable_sku,
    ANY_VALUE(facility_name)                            AS facility,
    ANY_VALUE(system_of_origin)                         AS system,
    ANY_VALUE(item_name)                                AS item_name,
    ANY_VALUE(consumable_uom)                           AS ruom,
    SUM(consumable_quantity_change)                     AS received_qty,
    DATE(MIN(datetime_utc))                             AS first_receipt_date,
    DATE(MAX(datetime_utc))                             AS last_receipt_date,
    ANY_VALUE(l1_action HAVING MAX consumable_quantity_change) AS move_l1,
    ANY_VALUE(l2_action HAVING MAX consumable_quantity_change) AS move_l2
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Purchase Order'
    AND consumable_sku IS NOT NULL
    AND DATE(datetime_utc) = run_date
  GROUP BY po, consumable_sku
),

po_lines AS (   -- how much each (PO, item) actually ORDERS (summed across the PO's lines)
  SELECT
    po,
    consumable_sku,
    SUM(consumable_sku_qty)   AS ordered_qty,
    ANY_VALUE(consumable_uom) AS ordered_uom
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase'
    AND consumable_sku IS NOT NULL
  GROUP BY po, consumable_sku
),

po_exists AS (   -- POs that actually exist
  SELECT
    po,
    ANY_VALUE(supplier_name) AS supplier
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Purchase'
  GROUP BY po
),

flagged AS (
  SELECT
    l.*,
    pe.supplier,
    pl.ordered_qty,
    pl.ordered_uom,
    (pl.consumable_sku IS NOT NULL) AS on_po
  FROM led l
  JOIN po_exists pe USING (po)                              -- the PO is real …
  LEFT JOIN po_lines pl
    ON l.po = pl.po AND l.consumable_sku = pl.consumable_sku
  WHERE COALESCE(pl.ordered_qty, 0) <= 0                    -- … but it orders none of this item
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                               AS total_matches,
    ROW_NUMBER() OVER (ORDER BY last_receipt_date DESC) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY last_receipt_date DESC
```

### Plain-English walkthrough

This rule answers: *"we received this item against PO #12345 — but was this item ever actually
ordered on PO #12345?"* That needs both tables: the **ledger** (what was received) and the **PO
table** (what was ordered). It's built in named steps.

1. **`run_date` = yesterday.**

2. **`led` — what got received against POs yesterday.** From the ledger, one row per (PO, item)
   received yesterday, with the net quantity and triage details (facility, system, item name, the
   dominant receiving action, first/last receipt dates).

3. **`po_lines` — how much each (PO, item) actually orders.** For every (PO, item) on a purchase
   order's lines, sum `consumable_sku_qty` to get the **ordered quantity**. Think of this as the guest
   list *with a headcount*: not just "is this item invited," but "how many were ordered."

4. **`po_exists` — which POs are real.** The set of PO numbers that exist at all (plus the supplier).

5. **`flagged` — the match logic (this is the clever part).** Two joins do the work:
   - `JOIN po_exists … USING (po)` — first confirm the **PO is real**. (If the PO itself didn't
     exist, that's a *different* problem — a missing PO, not a wrong item — so we require it to exist
     here.)
   - `LEFT JOIN po_lines … ON po AND consumable_sku` then **`WHERE COALESCE(pl.ordered_qty,0) <= 0`** —
     the `LEFT JOIN` looks the received item up on the PO's lines; if it isn't there, `pl.ordered_qty`
     comes back empty (`NULL`), and `COALESCE(…,0)` turns that into `0`. So the filter keeps receipts
     where the PO orders **zero or none** of the item — covering **both** breaks at once: the item is
     *not on the PO at all* (NULL → 0), **or** it's *on a line ordered for 0*. In plain terms: "the PO
     is real, but it orders none of this item — yet we received it." The zero-order case matters
     because Ship Hero can auto-create a receive-line with order qty 0 for an unexpected item, and if
     nothing was ordered we may never invoice the vendor.

6. **`ranked` + final line — count, cap at 500, newest-first.**

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** PO Table (`int_ledger_purchase_orders`).
**Join keys:** `ref_order_id` ⇄ `po` (the order) and `consumable_sku` ⇄ `consumable_sku` (the item).

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `ref_order_id` (ledger) | The PO the receipt was booked against. | **Join key** — must exist in the PO table. |
| `consumable_sku` (ledger) | The item that was received. | **The check** — the PO must order a positive quantity of it. |
| `datetime_utc` (ledger) | When it was received. | **Filter** — yesterday; sets the receipt dates. |
| `consumable_quantity_change` (ledger) | Quantity received. | Net received qty shown on the ticket. |
| `po`, `consumable_sku` (PO) | The order's lines (what was ordered). | The "guest list" the received item is matched against. |
| `consumable_sku_qty` (PO) | Quantity ordered on the PO line. | **The check** — summed per (PO, item); `<= 0` (or no line) is a break. |
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
| **Jonny Signoff** | 2026-07-15 |
| **Live status** | 🟢 **Live — runs daily.** Flagged **1** on yesterday's data; it fires whenever a wasted item has no ERP cost record. |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- A consumable_sku with waste/adjust activity that has NO row in the ERP standard-cost table
-- (ITEMID), so its waste can't be valued. LEFT JOIN waste-active SKUs -> cost; flag the misses.
SELECT w.consumable_sku
FROM (waste-active consumable_sku) w
LEFT JOIN (erp standard cost, ITEMID) c ON CAST(w.consumable_sku AS STRING) = c.ITEMID
WHERE c.ITEMID IS NULL
```

*(The two parenthesized inputs are spelled out in full in the live query below — `waste` and `cost`.)*

#### Live finder SQL (what runs daily)

```sql
-- Waste-active consumable_sku with NO ERP standard-cost record (no ITEMID match).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH cost AS (   -- latest-activated ERP standard cost per item (see "Where the standard cost comes from")
  SELECT
    ITEMID,
    AVG(UnitPrice)    AS unit_cost,
    ANY_VALUE(UNITID) AS cost_uom
  FROM (
    SELECT
      p.ITEMID,
      SAFE_DIVIDE(p.PRICE, p.PRICEUNIT) AS UnitPrice,
      p.UNITID
    FROM `wonder-raw-prod.erp_prod_batch.inventitempriceftistaging` AS p
    INNER JOIN (
      SELECT
        MAX(price.ActivationDate) AS ActivationDate,
        MAX(price.CREATEDTIME)    AS CREATEDTIME,
        price.ITEMID,
        price.INVENTDIMID,
        price.DATAAREAID
      FROM `wonder-raw-prod.erp_prod_batch.inventitempriceftistaging` AS price
      INNER JOIN `wonder-raw-prod.erp_prod_batch.inventdimftistaging` AS dim
        ON dim.INVENTDIMID = price.INVENTDIMID AND LOWER(dim.INVENTDIMDATAAREAID) = LOWER(price.DATAAREAID)
        AND LOWER(dim.INVENTSITEID) = 'control'
      GROUP BY price.ITEMID, price.DATAAREAID, price.INVENTDIMID
    ) m
      ON m.ITEMID = p.ITEMID AND m.ActivationDate = p.ActivationDate AND m.CREATEDTIME = p.CREATEDTIME
      AND LOWER(m.INVENTDIMID) = LOWER(p.INVENTDIMID) AND LOWER(m.DATAAREAID) = LOWER(p.DATAAREAID)
  )
  GROUP BY ITEMID
),

waste AS (   -- items with waste/adjustment activity yesterday, and how much was lost
  SELECT
    consumable_sku,
    ANY_VALUE(item_name)        AS item_name,
    ANY_VALUE(consumable_uom)   AS consumable_uom,
    ANY_VALUE(facility_name)    AS facility,
    ANY_VALUE(facility_type)    AS facility_type,
    ANY_VALUE(system_of_origin) AS system,
    SUM(IF(consumable_quantity_change < 0, -consumable_quantity_change, 0)) AS waste_qty,
    DATE(MIN(datetime_utc))     AS first_seen,
    DATE(MAX(datetime_utc))     AS last_seen
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE l1_action = 'Adjust'
    AND l2_action NOT IN ('Move From','Move To','Update Received Order','Shelf Life Extension')
    AND consumable_sku IS NOT NULL
    AND DATE(datetime_utc) = run_date
  GROUP BY consumable_sku
),

flagged AS (   -- keep the wasted items with NO cost record
  SELECT w.*
  FROM waste w
  LEFT JOIN cost c ON CAST(w.consumable_sku AS STRING) = c.ITEMID
  WHERE c.ITEMID IS NULL
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                        AS total_matches,
    ROW_NUMBER() OVER (ORDER BY waste_qty DESC) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
ORDER BY waste_qty DESC
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
| **Jonny Signoff** | 2026-07-15 |
| **Live status** | 🟢 **Live — runs daily.** Flagged **4** on yesterday's data. There's a large standing backlog (600+ items); the daily run tickets a **sample of up to 5** of the day's active zero-cost items while the program works through it. |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Framework #66: a consumable_sku active in the ledger whose ERP standard cost (PRICE/PRICEUNIT)
-- is 0 or NULL — can't be costed. JOIN ledger SKUs -> cost; flag unit_cost IS NULL OR = 0.
SELECT
  l.consumable_sku,
  c.unit_cost
FROM (ledger consumable_sku) l
JOIN (erp standard cost) c ON CAST(l.consumable_sku AS STRING) = c.ITEMID
WHERE c.unit_cost IS NULL OR c.unit_cost = 0
```

#### Live finder SQL (what runs daily)

```sql
-- Ledger-active consumable_sku whose ERP standard cost is 0/NULL (sample of 5 of the 600+ backlog).
DECLARE run_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);  -- yesterday

WITH cost AS (   -- latest-activated ERP standard cost per item (identical to COST-01's `cost` step)
  SELECT
    ITEMID,
    AVG(UnitPrice)    AS unit_cost,
    ANY_VALUE(UNITID) AS cost_uom
  FROM (
    SELECT
      p.ITEMID,
      SAFE_DIVIDE(p.PRICE, p.PRICEUNIT) AS UnitPrice,
      p.UNITID
    FROM `wonder-raw-prod.erp_prod_batch.inventitempriceftistaging` AS p
    INNER JOIN (
      SELECT
        MAX(price.ActivationDate) AS ActivationDate,
        MAX(price.CREATEDTIME)    AS CREATEDTIME,
        price.ITEMID,
        price.INVENTDIMID,
        price.DATAAREAID
      FROM `wonder-raw-prod.erp_prod_batch.inventitempriceftistaging` AS price
      INNER JOIN `wonder-raw-prod.erp_prod_batch.inventdimftistaging` AS dim
        ON dim.INVENTDIMID = price.INVENTDIMID AND LOWER(dim.INVENTDIMDATAAREAID) = LOWER(price.DATAAREAID)
        AND LOWER(dim.INVENTSITEID) = 'control'
      GROUP BY price.ITEMID, price.DATAAREAID, price.INVENTDIMID
    ) m
      ON m.ITEMID = p.ITEMID AND m.ActivationDate = p.ActivationDate AND m.CREATEDTIME = p.CREATEDTIME
      AND LOWER(m.INVENTDIMID) = LOWER(p.INVENTDIMID) AND LOWER(m.DATAAREAID) = LOWER(p.DATAAREAID)
  )
  GROUP BY ITEMID
),

led AS (   -- every item active in the ledger yesterday
  SELECT
    consumable_sku,
    ANY_VALUE(item_name)        AS item_name,
    ANY_VALUE(consumable_uom)   AS consumable_uom,
    ANY_VALUE(facility_name)    AS facility,
    ANY_VALUE(facility_type)    AS facility_type,
    ANY_VALUE(system_of_origin) AS system,
    DATE(MAX(datetime_utc))     AS last_seen
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE consumable_sku IS NOT NULL
    AND DATE(datetime_utc) = run_date
  GROUP BY consumable_sku
),

flagged AS (   -- items that HAVE a cost record, but the cost is 0/NULL
  SELECT
    l.*,
    c.unit_cost,
    c.cost_uom
  FROM led l
  JOIN cost c ON CAST(l.consumable_sku AS STRING) = c.ITEMID
  WHERE c.unit_cost IS NULL OR c.unit_cost = 0
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                        AS total_matches,
    ROW_NUMBER() OVER (ORDER BY last_seen DESC) AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 5
ORDER BY last_seen DESC
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

## XFER-01 · Transfer Order Missing

> **In one sentence:** find items picked (Transfer Out) against a Transfer Order id that has no
> matching record in the orders table — picking against a transfer order that doesn't exist.

### At a glance

| | |
|---|---|
| **Rule number** | XFER-01 |
| **Rule type** | `REFERENTIAL` (a "this value must exist in the other table" check) |
| **Severity** | **High** — 1-day SLA |
| **Owner / routed team** | SC Product (IMS) |
| **Default assignee** | Sarah Chen |
| **Jira** | Component **Transfer Orders** |
| **Source tables** | Inventory Ledger **⋈** PO Table (joined; transfer orders share the PO table, keyed by `order_type='Transfer'`) |
| **Live status** | 🟢 **Live — runs daily.** Re-enabled 2026-08-13. Was paused ("per Pavel: transfer orders are out of scope for now") because the naive join fired on every Transfer Out from the synthetic **Digital Transfer Warehouse** facility (`system_of_origin='digital_transfer_warehouse'`) — an in-transit staging facility whose freetext ad hoc labels (`"Instacart"`, `"Sesame general"`, `"BRFC - <date>"`, recount tags) never get a master transfer-order record, so **100% of them false-positived** (verified live: ~5–30/day of pure noise). Excluding that facility drops daily volume to **0–19/day** of genuine orphan picks — mostly at Arcadia, referencing real transferred items with no matching transfer order. |

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Catalog XFER-01: a Transfer Out pick references a Transfer Order id not in the
-- transfer-order population (orders table, order_type='Transfer'). Excludes the synthetic
-- Digital Transfer Warehouse facility (freetext ad hoc labels never get a master TO record).
WITH picks AS (
  SELECT DISTINCT ref_order_id AS to_id
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action = 'Transfer Out'
    AND ref_order_id IS NOT NULL
    AND system_of_origin != 'digital_transfer_warehouse'
),

to_pop AS (   -- every transfer-order id that actually exists
  SELECT DISTINCT po AS to_id
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
)

SELECT p.to_id
FROM picks p
LEFT JOIN to_pop t USING (to_id)
WHERE t.to_id IS NULL
```

#### Live finder SQL (what runs daily)

```sql
-- XFER-01: a Transfer Out pick references a Transfer Order id not in the transfer-order
-- population (orders table, order_type='Transfer'). One row per orphan transfer order.
WITH picks AS (
  SELECT
    ref_order_id                    AS to_id,
    COUNT(DISTINCT consumable_sku)  AS skus_picked,
    ANY_VALUE(item_name)            AS sample_item,
    ANY_VALUE(facility_name)        AS facility,
    ANY_VALUE(system_of_origin)     AS system,
    SUM(consumable_quantity_change) AS net_qty,
    DATE(MIN(datetime_utc))         AS first_seen,
    DATE(MAX(datetime_utc))         AS last_seen,
    ANY_VALUE(l1_action)            AS move_l1,
    ANY_VALUE(l2_action)            AS move_l2
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action = 'Transfer Out'
    AND ref_order_id IS NOT NULL
    AND system_of_origin != 'digital_transfer_warehouse'
    AND DATE(datetime_utc) = @run_date
  GROUP BY to_id
),

to_pop AS (   -- every transfer-order id that actually exists
  SELECT DISTINCT po AS to_id
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
),

flagged AS (
  SELECT p.*
  FROM picks p
  LEFT JOIN to_pop t USING (to_id)
  WHERE t.to_id IS NULL
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                        AS total_matches,
    ROW_NUMBER() OVER (ORDER BY last_seen DESC)  AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY last_seen DESC
```

### Plain-English walkthrough

This rule answers: *"this item was picked against Transfer Order #XYZ — but does Transfer Order
#XYZ actually exist?"* Transfer orders don't have their own table; they live in the PO table
(`int_ledger_purchase_orders`) alongside purchase orders, distinguished by `order_type='Transfer'`
(vs `'Purchase'`), with the transfer-order id in the same `po` column.

1. **`picks` — every Transfer Out yesterday, grouped by transfer-order id.** From the ledger,
   filter to `ref_order_type='Transfer Order'` and `l2_action='Transfer Out'` (the pick leg, not
   the receiving leg) with a non-null `ref_order_id`. **Excludes `system_of_origin =
   'digital_transfer_warehouse'`** — see the note below on why.

2. **`to_pop` — every transfer-order id that actually exists.** The set of `po` values in the PO
   table where `order_type='Transfer'`.

3. **`flagged` — `LEFT JOIN … WHERE t.to_id IS NULL`.** A pick whose transfer-order id has no
   match in `to_pop` is an orphan — items are moving against a transfer order that was never
   created (or never synced).

4. **`ranked` + final line — count, cap at 500, newest-first.**

**Why the Digital Transfer Warehouse exclusion matters.** `Digital Transfer Warehouse` is a
synthetic in-transit staging facility (`facility_id='FAC_DIGITAL_TRANSFER'`,
`facility_type='In-Transit'`), not a physical location. Its Transfer Out rows use freetext,
human-entered labels — `"Instacart"`, `"Sesame general"`, `"BRFC - August 12, 2026 (3)"`,
`"Mayonnaise (1 gal) - recount PO"` — for digital-channel and recount movements that are never
going to get a master transfer-order record, because there isn't a real transfer order behind
them. Checked live: every single one of these is an "orphan" by construction, and they made up
the large majority of daily hits before the exclusion. Real, numbered transfer orders (e.g.
`PO-390894`, `G-2625238` style ids) match the population reliably when they exist — this is a
targeted exclusion of one non-transfer facility, not a weakening of the underlying check.

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** PO Table
(`int_ledger_purchase_orders`, filtered to `order_type='Transfer'`).
**Join key:** `ref_order_id` (ledger) ⇄ `po` (PO table).

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `ref_order_type` (ledger) | What kind of order this movement references. | **Filter** — `'Transfer Order'`. |
| `l2_action` (ledger) | The specific movement type. | **Filter** — `'Transfer Out'` (the pick leg). |
| `ref_order_id` (ledger) | The transfer-order id the pick was booked against. | **Join key** — must exist in the PO table's transfer population. |
| `system_of_origin` (ledger) | Which system produced the row. | **Exclusion filter** — drops `'digital_transfer_warehouse'` (ad hoc, no master TO record by design). |
| `po` (PO table) | The order id. | **Join key** — the transfer-order population. |
| `order_type` (PO table) | `'Purchase'` or `'Transfer'`. | **Filter** — scopes the population to real transfer orders. |

### Example of a flagged record (from live data)

Live BigQuery, 2026-08-07, Arcadia:

| Field | Value |
|---|---|
| `to_id` (transfer order) | `DISH809` (no match in the transfer population ✗) |
| Items picked | 6 distinct SKUs, incl. `Cookies & Cream 8/14oz` |
| `facility` | `Arcadia` |
| `move` | Transfer Out |

**Why it's flagged:** items were picked and moved out against transfer order `DISH809`, but no
transfer order with that id exists in `int_ledger_purchase_orders`. Either the transfer order was
never created before the pick happened, or it never synced — SC Product (IMS) needs to reconcile
which.

---

## XFER-02 · SKU Not on Transfer Order

> **In one sentence:** find items picked (Transfer Out) against a Transfer Order that **exists**,
> but that orders **none of this item** — a 3-way-match break, the transfer-order sibling of PO-14.

### At a glance

| | |
|---|---|
| **Rule number** | XFER-02 |
| **Rule type** | `REFERENTIAL` (a "this value must exist in the other table" check) |
| **Severity** | **High** — 1-day SLA |
| **Owner / routed team** | Field Ops |
| **Default assignee** | Priya Nair |
| **Jira** | Component **Transfers** |
| **Source tables** | Inventory Ledger **⋈** PO Table (joined; transfer orders share the PO table, keyed by `order_type='Transfer'`) |
| **Live status** | 🟢 **Live — runs daily.** Added 2026-08-13, right after XFER-01. Excludes Digital Transfer Warehouse and TOs that don't exist at all (that's XFER-01's job — this rule requires the TO to exist first). **Joined on `ims_sku`, not `consumable_sku`** — see below. Currently finds **0 in the last 30 days** on live data (243 all-time, spread thin across DISH/Arcadia/Millington) — a low-volume safety net, kept live to catch it the moment it recurs, same pattern as PO-13. |

### Why `ims_sku`, not `consumable_sku`

The obvious join key — `consumable_sku`, same as PO-14 uses for purchase orders — is a **trap**
here. Checked live on one sample day (2026-08-07, DISH): joining Transfer Out picks to TO lines on
`consumable_sku` produced **14,679 "orphans" out of 20,228 picks (72%)** where the transfer order
unambiguously existed. Spot-checking one: a pick against `PO-425282` for `consumable_sku='4000997'`
had no line for that sku on the TO — but the TO *did* have a line for `ims_sku='4200434'` at
`consumable_sku='4200434'`, and the ledger pick's own `ims_sku` was also `4200434`. The ledger's
`consumable_sku` is a per-system **translation** that doesn't line up 1:1 with the TO table's
`consumable_sku` for the same item; `ims_sku` is the raw id both tables share, and re-running the
exact same day's check keyed on `ims_sku` found **0** false positives. This is the identical lesson
already learned on PO-03 (see the "Refined per Jonny Li" note in that section) — it just hadn't
been applied to the transfer side yet.

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Catalog XFER-02: a Transfer Out pick against a Transfer Order that EXISTS, but the TO
-- orders none of that item (not on its lines, or on a line ordered for 0). Excludes Digital
-- Transfer Warehouse and TOs that don't exist at all (XFER-01's job). Joined on ims_sku, not
-- consumable_sku — verified live that consumable_sku is a per-system translation that doesn't
-- line up 1:1 between the ledger and the TO table (72% false-positive rate on one sample day);
-- ims_sku is the raw shared id and matches cleanly. Same lesson as PO-03's ims_sku re-key.
WITH picks AS (
  SELECT DISTINCT ref_order_id AS to_id, ims_sku
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action = 'Transfer Out'
    AND ref_order_id IS NOT NULL
    AND ims_sku IS NOT NULL
    AND system_of_origin != 'digital_transfer_warehouse'
),

to_lines AS (   -- how much of each item each transfer order actually orders
  SELECT
    po,
    ims_sku,
    SUM(consumable_sku_qty) AS ordered_qty
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
    AND ims_sku IS NOT NULL
  GROUP BY po, ims_sku
),

to_exists AS (   -- the set of real transfer-order ids
  SELECT DISTINCT po
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
)

SELECT p.to_id, p.ims_sku
FROM picks p
JOIN to_exists e ON p.to_id = e.po
LEFT JOIN to_lines l ON p.to_id = l.po AND p.ims_sku = l.ims_sku
WHERE COALESCE(l.ordered_qty, 0) <= 0
```

#### Live finder SQL (what runs daily)

```sql
-- XFER-02: an item picked (Transfer Out) against a Transfer Order that EXISTS, but the TO
-- orders none of that item. One row per (transfer order, ims_sku).
WITH picks AS (
  SELECT
    ref_order_id                    AS to_id,
    ims_sku,
    ANY_VALUE(consumable_sku)       AS consumable_sku,
    ANY_VALUE(item_name)            AS item_name,
    ANY_VALUE(facility_name)        AS facility,
    ANY_VALUE(system_of_origin)     AS system,
    SUM(consumable_quantity_change) AS net_qty,
    DATE(MIN(datetime_utc))         AS first_seen,
    DATE(MAX(datetime_utc))         AS last_seen,
    ANY_VALUE(l1_action)            AS move_l1,
    ANY_VALUE(l2_action)            AS move_l2
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action = 'Transfer Out'
    AND ref_order_id IS NOT NULL
    AND ims_sku IS NOT NULL
    AND system_of_origin != 'digital_transfer_warehouse'
    AND DATE(datetime_utc) = @run_date
  GROUP BY to_id, ims_sku
),

to_lines AS (   -- how much of each item each transfer order actually orders
  SELECT
    po,
    ims_sku,
    SUM(consumable_sku_qty) AS ordered_qty
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
    AND ims_sku IS NOT NULL
  GROUP BY po, ims_sku
),

to_exists AS (   -- the set of real transfer-order ids
  SELECT DISTINCT po
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
),

flagged AS (
  SELECT
    p.*,
    (l.ims_sku IS NOT NULL) AS on_to,
    l.ordered_qty
  FROM picks p
  JOIN to_exists e ON p.to_id = e.po
  LEFT JOIN to_lines l ON p.to_id = l.po AND p.ims_sku = l.ims_sku
  WHERE COALESCE(l.ordered_qty, 0) <= 0
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                        AS total_matches,
    ROW_NUMBER() OVER (ORDER BY last_seen DESC)  AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY last_seen DESC
```

### Plain-English walkthrough

This rule answers: *"this item was picked against Transfer Order #XYZ, and #XYZ is real — but did
#XYZ actually order this item?"*

1. **`picks` — every (transfer order, ims_sku) picked yesterday.** Same filter as XFER-01
   (`ref_order_type='Transfer Order'`, `l2_action='Transfer Out'`, excludes Digital Transfer
   Warehouse), but keyed on `ims_sku` instead of `ref_order_id` alone.

2. **`to_lines` — how much of each item each transfer order actually orders.** Summed
   `consumable_sku_qty` per `(po, ims_sku)` on the TO's lines.

3. **`to_exists`** — the set of real transfer-order ids, same population XFER-01 checks against.

4. **`flagged` — the match logic, identical shape to PO-14's:**
   - `JOIN to_exists … ON to_id = po` — require the TO to be **real** first. If it weren't, that's
     XFER-01's problem, not this rule's — this prevents the two rules from double-ticketing the
     same root cause.
   - `LEFT JOIN to_lines … WHERE COALESCE(ordered_qty, 0) <= 0` — the TO orders zero or none of
     this item (not on its lines at all, or on a line ordered for 0).

5. **`ranked` + final line** — count, cap at 500, newest-first.

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** PO Table
(`int_ledger_purchase_orders`, filtered to `order_type='Transfer'`).
**Join keys:** `ref_order_id` ⇄ `po` (the order) and **`ims_sku` ⇄ `ims_sku`** (the item — not
`consumable_sku`, see above).

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `ref_order_id` (ledger) | The transfer order the pick was booked against. | **Join key** — must exist (`to_exists`). |
| `ims_sku` (ledger) | The raw system item id. | **Join key** — must have a positive-qty line on the TO. |
| `consumable_sku` (ledger) | The translated item id. | **Not used for joining** — shown on the ticket for context only. |
| `system_of_origin` (ledger) | Which system produced the row. | **Exclusion filter** — drops `'digital_transfer_warehouse'`. |
| `po`, `ims_sku` (PO table) | The TO's lines (what was ordered). | The "guest list" the picked item is matched against. |
| `consumable_sku_qty` (PO table) | Quantity ordered on the TO line. | **The check** — summed per (TO, `ims_sku`); `<= 0` (or no line) is a break. |

### Example of a flagged record (from live data)

Live BigQuery, 2026-05-23, Arcadia — Transfer Order `TO-DISH_DTC1333`:

| Field | Value |
|---|---|
| `to_id` (transfer order) | `TO-DISH_DTC1333` (exists ✓) |
| `ims_sku` / `item_name` | `W34625` / `Marinara Sauce, 9 LB, Frozen` |
| On the TO's lines? | **No** ← **the problem** |
| `net_qty_change` | `-979,758.72` (base unit) |
| `system` | `Shiphero` |

**Why it's flagged:** the transfer order is valid, but this item was never ordered on it — the
same 3-way-match break PO-14 catches on the purchase side, just for transfers. This TO had **11**
items flagged this way the same day, all against the same TO id — worth a single reconciliation
pass rather than 11 separate tickets' worth of digging.

---

## XFER-05 · Received SKU Not on Transfer Order

> **In one sentence:** find items **received** (Transfer In, or Received at Pantry/HDR) against a
> Transfer Order that **exists**, but that orders **none of this item** — the receiving-side
> sibling of XFER-02.

### At a glance

| | |
|---|---|
| **Rule number** | XFER-05 (framework catalog numbering — not built in numeric order; XFER-03/04 are quantity/aging checks, not yet built) |
| **Rule type** | `REFERENTIAL` (a "this value must exist in the other table" check) |
| **Severity** | **High** — 1-day SLA |
| **Owner / routed team** | SC Product (IMS) |
| **Default assignee** | Marcus Webb |
| **Jira** | Component **3-Way Match** |
| **Source tables** | Inventory Ledger **⋈** PO Table (joined; transfer orders share the PO table, keyed by `order_type='Transfer'`) |
| **Live status** | 🟢 **Live — runs daily.** Added 2026-08-13. Covers both receiving legs tagged `ref_order_type='Transfer Order'`: `l2_action='Transfer In'` (DISH-type facilities) and `l2_action='Received'` (Pantry/HDR selling units). Excludes Digital Transfer Warehouse and TOs that don't exist (XFER-01's job). **Uses a different join predicate than XFER-02** — see below, this one is not a simple `ims_sku` equality. Live volume: **40–200/day** across ~180 HDR selling units plus DISH — a real, moderate-volume defect rate (not systemic noise). |

### Why this rule needed a different join than XFER-02 (the "-N" suffix)

XFER-02 (picking) joins cleanly on plain `ims_sku` equality. Naively reusing that same join for
receiving looked reasonable — but checked live, it produced a **15–70% false-positive rate at
literally every one of ~180 HDR selling units**, every day. Root cause: **827,000 of 22.48M**
transfer-order lines (concentrated in Pantry/HDR frozen "F" items) carry a **`-N` case-multiplier
suffix** on `ims_sku` — e.g. a TO line reads `ims_sku='4200584F-2'` for an item the ledger's
receiving leg reports as the bare `ims_sku='4200584F'`. Two candidate fixes were tested against
live data before picking one:

- **Strip the suffix on the TO side** (`GROUP BY REGEXP_REPLACE(ims_sku, r'-[0-9]+$', '')`) —
  fixed receiving completely (0 false positives), **but retested against XFER-02's picking-side
  query and broke it**: 67,755 new false orphans on the same 30-day window that was previously
  clean. Stripping merges genuinely distinct suffixed lines into one bucket, which is safe for
  receiving's aggregate-sum check but corrupts picking's.
- **Match exact-OR-suffixed per row** (`l.ims_sku = p.ims_sku OR l.ims_sku LIKE CONCAT(p.ims_sku,
  '-%')`), summing only the matching lines — fixed receiving (0 false positives, same result as
  stripping) **with zero effect on picking** (still 0/512,802 false positives on the same 30-day
  window, because it never merges unrelated lines together). This is the predicate XFER-05 uses.
  XFER-02 doesn't need it and wasn't changed.

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Catalog XFER-05: an item RECEIVED (Transfer In, or Received at Pantry/HDR) against a
-- Transfer Order that EXISTS, but the TO orders none of that item. Receiving-side sibling
-- of XFER-02. Excludes Digital Transfer Warehouse and TOs that don't exist (XFER-01's job).
-- Join is exact-OR-suffixed ims_sku (l.ims_sku = p.ims_sku OR l.ims_sku LIKE p.ims_sku||'-%'),
-- NOT plain ims_sku and NOT a stripped-suffix match — see the write-up above.
WITH picks AS (
  SELECT DISTINCT ref_order_id AS to_id, ims_sku
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action IN ('Transfer In', 'Received')
    AND ref_order_id IS NOT NULL
    AND ims_sku IS NOT NULL
    AND system_of_origin != 'digital_transfer_warehouse'
),

to_exists AS (   -- the set of real transfer-order ids
  SELECT DISTINCT po
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
)

SELECT p.to_id, p.ims_sku
FROM picks p
JOIN to_exists e ON p.to_id = e.po
WHERE COALESCE((
  SELECT SUM(l.consumable_sku_qty)
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders` l
  WHERE l.po = p.to_id
    AND l.order_type = 'Transfer'
    AND (l.ims_sku = p.ims_sku OR l.ims_sku LIKE CONCAT(p.ims_sku, '-%'))
), 0) <= 0
```

#### Live finder SQL (what runs daily)

```sql
-- XFER-05: an item received (Transfer In / Received) against a real Transfer Order that
-- orders none of this item. One row per (transfer order, ims_sku).
WITH picks AS (
  SELECT
    ref_order_id                    AS to_id,
    ims_sku,
    ANY_VALUE(consumable_sku)       AS consumable_sku,
    ANY_VALUE(item_name)            AS item_name,
    ANY_VALUE(facility_name)        AS facility,
    ANY_VALUE(system_of_origin)     AS system,
    SUM(consumable_quantity_change) AS net_qty,
    DATE(MIN(datetime_utc))         AS first_seen,
    DATE(MAX(datetime_utc))         AS last_seen,
    ANY_VALUE(l1_action)            AS move_l1,
    ANY_VALUE(l2_action)            AS move_l2
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action IN ('Transfer In', 'Received')
    AND ref_order_id IS NOT NULL
    AND ims_sku IS NOT NULL
    AND system_of_origin != 'digital_transfer_warehouse'
    AND DATE(datetime_utc) = @run_date
  GROUP BY to_id, ims_sku
),

to_exists AS (   -- the set of real transfer-order ids
  SELECT DISTINCT po
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
),

joined AS (   -- exact-or-suffixed ims_sku match against the TO's lines (see write-up above)
  SELECT
    p.to_id, p.ims_sku, p.consumable_sku, p.item_name, p.facility, p.system, p.net_qty,
    p.first_seen, p.last_seen, p.move_l1, p.move_l2,
    l.consumable_sku_qty
  FROM picks p
  JOIN to_exists e ON p.to_id = e.po
  LEFT JOIN `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders` l
    ON l.po = p.to_id
    AND l.order_type = 'Transfer'
    AND (l.ims_sku = p.ims_sku OR l.ims_sku LIKE CONCAT(p.ims_sku, '-%'))
),

agg AS (   -- re-aggregate: the exact-or-suffixed join can match more than one line per pick
  SELECT
    to_id,
    ims_sku,
    ANY_VALUE(consumable_sku)                  AS consumable_sku,
    ANY_VALUE(item_name)                       AS item_name,
    ANY_VALUE(facility)                        AS facility,
    ANY_VALUE(system)                          AS system,
    ANY_VALUE(net_qty)                         AS net_qty,
    ANY_VALUE(first_seen)                      AS first_seen,
    ANY_VALUE(last_seen)                       AS last_seen,
    ANY_VALUE(move_l1)                         AS move_l1,
    ANY_VALUE(move_l2)                         AS move_l2,
    SUM(consumable_sku_qty)                    AS ordered_qty,
    LOGICAL_OR(consumable_sku_qty IS NOT NULL) AS on_to
  FROM joined
  GROUP BY to_id, ims_sku
),

flagged AS (
  SELECT *
  FROM agg
  WHERE COALESCE(ordered_qty, 0) <= 0
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                        AS total_matches,
    ROW_NUMBER() OVER (ORDER BY last_seen DESC)  AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY last_seen DESC
```

### Plain-English walkthrough

1. **`picks`** — every (transfer order, `ims_sku`) received yesterday, either leg
   (`Transfer In` at DISH-type facilities, or `Received` at Pantry/HDR selling units), excluding
   Digital Transfer Warehouse.

2. **`to_exists`** — the same real-transfer-order population XFER-01/02 check against.

3. **`joined` + `agg`** — for each pick, `LEFT JOIN` the TO's lines using the **exact-or-suffixed**
   predicate, then re-aggregate (`SUM`/`ANY_VALUE`) back down to one row per (transfer order,
   `ims_sku`), since the join can match more than one line (e.g. a line at the bare id and another
   at a suffixed variant that both happen to apply — summing keeps the "total ordered" check
   correct rather than picking one arbitrarily).

4. **`flagged`** — `COALESCE(ordered_qty, 0) <= 0`: the TO orders zero or none of this item.

5. **`ranked` + final line** — count, cap at 500, newest-first.

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** PO Table
(`int_ledger_purchase_orders`, filtered to `order_type='Transfer'`).
**Join keys:** `ref_order_id` ⇄ `po` (the order) and **`ims_sku` ⇄ `ims_sku` (exact OR
`ims_sku` LIKE `ims_sku`+`'-%'`)** — not a plain equality, see above.

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `l2_action` (ledger) | The specific movement type. | **Filter** — `'Transfer In'` or `'Received'` (the two receiving legs). |
| `ref_order_id` (ledger) | The transfer order the receipt was booked against. | **Join key** — must exist (`to_exists`). |
| `ims_sku` (ledger) | The raw system item id, unsuffixed on this leg. | **Join key** — matched against the TO's lines, suffix-tolerant. |
| `system_of_origin` (ledger) | Which system produced the row. | **Exclusion filter** — drops `'digital_transfer_warehouse'`. |
| `po`, `ims_sku` (PO table) | The TO's lines. `ims_sku` here may carry a `-N` case-multiplier suffix. | The "guest list" the received item is matched against. |
| `consumable_sku_qty` (PO table) | Quantity ordered on the TO line. | **The check** — summed across all matching (exact + suffixed) lines; `<= 0` is a break. |

### Example of a flagged record (from live data)

Live BigQuery, 2026-08-07, DISH:

| Field | Value |
|---|---|
| `to_id` (transfer order) | `260806CK1-SHIP00029` (exists ✓) |
| `ims_sku` / `item_name` | `4200781-20` / `Steamed Jasmine Rice (270 g)` |
| On the TO's lines? | **No** ← **the problem** |
| `net_qty_change` | `+194,400` (base unit) |
| `system` | `Shiphero` |
| `movement` | Add / Transfer In |

**Why it's flagged:** the transfer order is valid, but this item — a large received quantity —
was never ordered on it. 76 items flagged this way across DISH and Pantry/HDR selling units the
same day, a moderate steady-state rate worth routing to SC Product (IMS) for reconciliation.

---

## XFER-04 · Transfer Order No Pick Activity

> **In one sentence:** find Transfer Orders still in an early lifecycle status (not yet shipped,
> not cancelled) that have had **zero pick activity** more than **Y days** (default 2,
> **Admin-editable**) after being created.

### At a glance

| | |
|---|---|
| **Rule number** | XFER-04 |
| **Rule type** | `AGING` (a "too much time has passed with nothing happening" check) |
| **Severity** | **Medium** — 2-day SLA |
| **Owner / routed team** | Field Ops |
| **Default assignee** | Priya Nair |
| **Jira** | Component **Transfers** |
| **Source tables** | PO Table (population, `order_type='Transfer'`) **⋈** Inventory Ledger (activity check) |
| **Threshold** | **Y = 2 days**, editable in **Admin → Transfer order aging** (`PUT /api/xfer-aging`, `app_setting.xfer_no_pick_days`) — takes effect on the next validation run, no restart needed. |
| **Live status** | 🟢 **Live — runs daily.** Added 2026-08-17. Current backlog: **150** (30-day lookback window), a believable ~10/day rate. |

### Why "picked" can't be judged from the ledger alone here

Every other transfer rule (XFER-01/02/05) treats "a ledger row with `l2_action='Transfer Out'`
exists" as the sole truth for "picked." Reusing that here looked reasonable but checked live, it
false-positived at scale: of Transfer Orders with **zero** matching ledger rows, **~94% are
already `status=CLOSED` or `RECEIVED`** in the orders table — i.e. they obviously already shipped,
they just never got a row in `consolidated_inventory_ledger` under that transfer-order id. One
example, `PO-431527` (status `CLOSED`), has **zero rows in the ledger under any action, ever** —
not a join-key formatting issue like the `ims_sku` cases on XFER-02/05, a genuine gap in what
syncs into the ledger for a meaningful slice of transfers. Flagging on ledger absence alone would
have produced ~300+/day of pure noise.

**The fix:** a Transfer Order counts as already-picked if **either** a ledger Transfer Out row
exists **or** its own status has already advanced past picking (`SHIPPED`, `PARTIALLY_SHIPPED`,
`RECEIVED`, `PARTIALLY_RECEIVED`, `CLOSED`, `PICKED`, `PACKED`, `PACKING`, `PLACED`). Dead orders
(`CANCELLED`, `CANCELED`, `VOIDED`, `VENDOR_REJECTED`) are excluded from consideration entirely —
not a "no pick activity" case, just not a candidate either way. With that filter, the genuinely
still-early-lifecycle population (statuses like `PENDING`, `PLANNED`, `VENDOR_ACCEPTED`,
`NOT_RECEIVED`, `EXCEPTION`) with real zero pick activity is a believable ~10/day.

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Catalog XFER-04: a Transfer Order still in an early lifecycle status (not yet shipped,
-- not cancelled/rejected) with ZERO Transfer Out ledger activity more than Y days after it
-- was created. A TO is also treated as already-picked if its own status has advanced past
-- picking — see the write-up above. Y defaults to 2, admin-editable.
WITH to_agg AS (
  SELECT
    po,
    MAX(DATE(po_date_utc))                  AS order_date,
    ARRAY_AGG(DISTINCT status IGNORE NULLS) AS statuses
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
    AND po IS NOT NULL
    AND TRIM(po) <> ''
  GROUP BY po
),

picked AS (   -- transfer orders with at least one real ledger Transfer Out row
  SELECT DISTINCT ref_order_id AS po
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action = 'Transfer Out'
    AND ref_order_id IS NOT NULL
)

SELECT t.po
FROM to_agg t
LEFT JOIN picked p USING (po)
WHERE p.po IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM UNNEST(t.statuses) s
    WHERE UPPER(s) IN (
      'CANCELLED', 'CANCELED', 'VOIDED', 'VENDOR_REJECTED',
      'SHIPPED', 'PARTIALLY_SHIPPED', 'RECEIVED', 'PARTIALLY_RECEIVED',
      'CLOSED', 'PICKED', 'PACKED', 'PACKING', 'PLACED'
    )
  )
  AND t.order_date IS NOT NULL
  AND t.order_date < DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
```

#### Live finder SQL (what runs daily)

```sql
-- XFER-04: current backlog of still-early-status Transfer Orders with no pick activity.
WITH to_agg AS (
  SELECT
    po,
    MAX(DATE(po_date_utc))                  AS order_date,
    ARRAY_AGG(DISTINCT status IGNORE NULLS) AS statuses,
    ANY_VALUE(destination_name)             AS facility,
    ANY_VALUE(destination_id)               AS facility_id,
    ANY_VALUE(po_source_system)             AS system
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
    AND po IS NOT NULL
    AND TRIM(po) <> ''
  GROUP BY po
),

picked AS (   -- transfer orders with at least one real ledger Transfer Out row
  SELECT DISTINCT ref_order_id AS po
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action = 'Transfer Out'
    AND ref_order_id IS NOT NULL
),

flagged AS (
  SELECT
    t.*,
    DATE_ADD(t.order_date, INTERVAL @no_pick_days DAY) AS breach_date,
    DATE_DIFF(@run_date, t.order_date, DAY)            AS days_since_order
  FROM to_agg t
  LEFT JOIN picked p USING (po)
  WHERE p.po IS NULL
    AND NOT EXISTS (
      SELECT 1 FROM UNNEST(t.statuses) s
      WHERE UPPER(s) IN (
        'CANCELLED', 'CANCELED', 'VOIDED', 'VENDOR_REJECTED',
        'SHIPPED', 'PARTIALLY_SHIPPED', 'RECEIVED', 'PARTIALLY_RECEIVED',
        'CLOSED', 'PICKED', 'PACKED', 'PACKING', 'PLACED'
      )
    )
    AND t.order_date IS NOT NULL
    AND t.order_date < DATE_SUB(@run_date, INTERVAL @no_pick_days DAY)
    AND t.order_date >= DATE_SUB(@run_date, INTERVAL 30 DAY)
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                          AS total_matches,
    ROW_NUMBER() OVER (ORDER BY order_date ASC)    AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY order_date ASC
```

### Plain-English walkthrough

1. **`to_agg`** — every Transfer Order, one row per `po`, with its most recent creation date and
   the full set of distinct statuses seen across its lines.
2. **`picked`** — the set of transfer-order ids with at least one real ledger Transfer Out row.
3. **`flagged`** — `LEFT JOIN … WHERE p.po IS NULL` (no ledger pick), **and** none of the order's
   statuses fall in the "already advanced or dead" list, **and** it's old enough
   (`order_date < run_date - Y days`) and recent enough to matter (`order_date >= run_date - 30
   days`, so the rule stays on the current backlog rather than the full historical population).
4. **`ranked` + final line** — count, cap at 500, oldest-first (the longest-waiting orders surface
   first, same convention as PO-07).

State-based, like PO-07/PO-08: this returns the **current** backlog each run, not just "new
today" — dedup on the app side prevents re-tickets, and the recheck auto-closes once a pick
appears or the status advances.

### Tables & columns used

**Tables:** PO Table (`int_ledger_purchase_orders`, `order_type='Transfer'`) **⋈** Inventory Ledger
(`consolidated_inventory_ledger`, activity check only).

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `po` (PO table) | The transfer order id. | Grain of the check; join key against the ledger. |
| `po_date_utc` (PO table) | When the order was created. | **The clock** — `order_date`, the aging baseline. |
| `status` (PO table) | The order's lifecycle status. | **The safety filter** — excludes dead and already-advanced orders (see write-up above). |
| `ref_order_type`, `l2_action`, `ref_order_id` (ledger) | Movement type and the order it references. | **The check** — `ref_order_type='Transfer Order'`, `l2_action='Transfer Out'`; absence = no pick. |

### Example of a flagged record (from live data)

Live BigQuery, run date 2026-08-16:

| Field | Value |
|---|---|
| `transfer_order` | `PO-390835` |
| `facility` | Arcadia |
| `to_status` | `NOT_RECEIVED` |
| `order_date` | 2026-07-17 |
| `days_since_order` | 30 |

**Why it's flagged:** created 30 days ago, still in an early (`NOT_RECEIVED`) status, and no
Transfer Out ledger row has ever been recorded against it — well past the 2-day threshold.

---

## XFER-07 · Transfer Picked — Not Received

> **In one sentence:** find real Transfer Orders that **were** picked but have had **zero
> receiving activity** more than **Z days** (default 2, **Admin-editable**) after the first pick.

### At a glance

| | |
|---|---|
| **Rule number** | XFER-07 |
| **Rule type** | `AGING` |
| **Severity** | **Medium** — 2-day SLA |
| **Owner / routed team** | Field Ops |
| **Default assignee** | Priya Nair |
| **Jira** | Component **Transfers** |
| **Source tables** | Inventory Ledger (pick + receipt activity) **⋈** PO Table (existence + status check) |
| **Threshold** | **Z = 2 days**, editable in **Admin → Transfer order aging** (`PUT /api/xfer-aging`, `app_setting.xfer_not_received_days`). |
| **Live status** | 🟢 **Live — runs daily.** Added 2026-08-17. Current backlog: **0** — a clean safety net, same shape as PO-13 (kept live even at zero so it catches it the moment it happens). |

### Why this one doesn't need the same status-based safety net as XFER-04

XFER-04's ledger-only definition broke because a real fraction of transfer orders complete their
whole lifecycle without ever touching the ledger. The receiving side doesn't have that problem:
checked live, **0 of 76,035** picked, non-cancelled transfer orders in a 90-day window lack a
matching `Transfer In` / `Received` ledger row. So XFER-07 stays ledger-only — pick date from the
ledger, receipt check from the ledger — with just a `status NOT IN ('CANCELLED','CANCELED',
'VOIDED')` filter (a cancelled-after-picking order is resolved, not stuck) and a requirement that
the transfer order actually exists (so this doesn't double-ticket XFER-01's job).

### The SQL

#### Catalog SQL (the documented definition)

```sql
-- Catalog XFER-07: a real Transfer Order (exists in the population) that WAS picked (a
-- Transfer Out ledger row exists) but has no Transfer In / Received ledger row more than Z
-- days after the first pick. Excludes cancelled/voided orders. Z defaults to 2, admin-editable.
WITH picked AS (
  SELECT
    ref_order_id            AS po,
    MIN(DATE(datetime_utc)) AS first_pick
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action = 'Transfer Out'
    AND ref_order_id IS NOT NULL
  GROUP BY ref_order_id
),

received AS (   -- transfer orders with at least one Transfer In / Received ledger row
  SELECT DISTINCT ref_order_id AS po
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action IN ('Transfer In', 'Received')
    AND ref_order_id IS NOT NULL
),

to_exists AS (   -- requires the order to be real (skips XFER-01's territory) + carries status
  SELECT
    po,
    ARRAY_AGG(DISTINCT status IGNORE NULLS) AS statuses
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
  GROUP BY po
)

SELECT pk.po
FROM picked pk
JOIN to_exists e USING (po)
LEFT JOIN received r USING (po)
WHERE r.po IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM UNNEST(e.statuses) s
    WHERE UPPER(s) IN ('CANCELLED', 'CANCELED', 'VOIDED')
  )
  AND pk.first_pick < DATE_SUB(CURRENT_DATE(), INTERVAL 2 DAY)
```

#### Live finder SQL (what runs daily)

```sql
-- XFER-07: current backlog of picked Transfer Orders with no receipt.
WITH picked AS (
  SELECT
    ref_order_id                AS po,
    MIN(DATE(datetime_utc))     AS first_pick,
    ANY_VALUE(facility_name)    AS facility,
    ANY_VALUE(system_of_origin) AS system
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action = 'Transfer Out'
    AND ref_order_id IS NOT NULL
  GROUP BY ref_order_id
),

received AS (   -- transfer orders with at least one Transfer In / Received ledger row
  SELECT DISTINCT ref_order_id AS po
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE ref_order_type = 'Transfer Order'
    AND l2_action IN ('Transfer In', 'Received')
    AND ref_order_id IS NOT NULL
),

to_exists AS (   -- requires the order to be real (skips XFER-01's territory) + carries status
  SELECT
    po,
    ARRAY_AGG(DISTINCT status IGNORE NULLS) AS statuses
  FROM `wonder-dw-prod-brd.inventory.int_ledger_purchase_orders`
  WHERE order_type = 'Transfer'
  GROUP BY po
),

flagged AS (
  SELECT
    pk.*,
    DATE_ADD(pk.first_pick, INTERVAL @not_received_days DAY) AS breach_date,
    DATE_DIFF(@run_date, pk.first_pick, DAY)                 AS days_since_pick
  FROM picked pk
  JOIN to_exists e USING (po)
  LEFT JOIN received r USING (po)
  WHERE r.po IS NULL
    AND NOT EXISTS (
      SELECT 1 FROM UNNEST(e.statuses) s
      WHERE UPPER(s) IN ('CANCELLED', 'CANCELED', 'VOIDED')
    )
    AND pk.first_pick < DATE_SUB(@run_date, INTERVAL @not_received_days DAY)
    AND pk.first_pick >= DATE_SUB(@run_date, INTERVAL 30 DAY)
),

ranked AS (
  SELECT
    *,
    COUNT(*)     OVER ()                        AS total_matches,
    ROW_NUMBER() OVER (ORDER BY first_pick ASC)  AS rn
  FROM flagged
)

SELECT * EXCEPT (rn)
FROM ranked
WHERE rn <= 500
ORDER BY first_pick ASC
```

### Plain-English walkthrough

1. **`picked`** — every transfer order with a real ledger Transfer Out row, and the date of its
   first one.
2. **`received`** — the set of transfer-order ids with at least one `Transfer In` / `Received`
   ledger row.
3. **`to_exists`** — requires the order to be real (skips XFER-01's territory) and carries status
   for the cancelled-order exclusion.
4. **`flagged`** — picked, not received, not cancelled, and old enough
   (`first_pick < run_date - Z days`) / recent enough (`>= run_date - 30 days`) to matter.
5. **`ranked` + final line** — count, cap at 500, oldest-first.

State-based like XFER-04/PO-07/PO-08 — current backlog each run; recheck auto-closes once a
receiving-leg ledger row appears.

### Tables & columns used

**Tables:** Inventory Ledger (`consolidated_inventory_ledger`) **⋈** PO Table
(`int_ledger_purchase_orders`, `order_type='Transfer'`, existence + status only).

| Column (table) | Plain meaning | Role in this rule |
|---|---|---|
| `ref_order_type`, `l2_action='Transfer Out'` (ledger) | The pick leg. | **The clock start** — `first_pick`. |
| `ref_order_id` (ledger) | The transfer order. | Join key against `to_exists` and `received`. |
| `l2_action IN ('Transfer In','Received')` (ledger) | The receiving leg. | **The check** — absence = not received. |
| `status` (PO table) | The order's lifecycle status. | **Exclusion filter** — drops cancelled/voided. |

### Example

Currently 0 in the live backlog — see the "why this doesn't need a safety net" note above for the
0/76,035 validation. When it does fire, the shape is identical to XFER-04's (transfer order,
facility, days since the triggering event, breach date).

---

## TWH-01 · Transfer Warehouse In/Out Balance

> **DRAFTED — NOT LIVE.** This rule is documented and query-tested against live BigQuery data, but
> deliberately **not enabled** and **not wired into the daily finder**. It's here for a data
> engineer to confirm the flow assumptions below before it goes anywhere near real tickets.

> **In one sentence:** find an item that shows up on **one** of the two Digital Transfer
> Warehouse legs (arrived / left) but is **completely missing** from the other — the pattern in
> the "starting warehouse → 2 digital movements → final warehouse" reference example, but looking
> **only** at the two middle (digital) legs, not the starting or ending warehouse.

### At a glance

| | |
|---|---|
| **Rule number** | TWH-01 (framework catalog — this is a separate family from XFER-0N, not one of the transfer-order rules built so far) |
| **Rule type** | `RECON_TRANSFER` (a two-leg reconciliation, not a referential or aging check) |
| **Severity** | High (proposed — not yet confirmed) |
| **Owner / routed team** | Field Ops / Priya Nair (proposed, matches the other Transfers-component routing) |
| **Source table** | Inventory Ledger only (`consolidated_inventory_ledger`) — no PO/TO table join |
| **Status** | 🔵 **Drafted, not live.** `Rule.enabled = False` in both `reference.py` and the DB; not present in `bq_finder._FINDERS`. Cannot fire even if something else flips the DB flag, because there is no finder function wired to it. |
| **Current (draft) numbers** | 30-day window, existence mismatch only, aged 3+ days: **5,404** "arrived, never left" (~180/day), **6,313** "left, never arrived" (~210/day). See the two correction write-ups below for how much these numbers moved during investigation — read those before trusting any number here. |

### What this is comparing (and why it's narrower than it sounds)

The reference example (a real 4-row ledger excerpt a data engineer shared) shows one transfer as
four ledger rows: **origin** facility Transfer Out → **DTW** Transfer In → **DTW** Transfer Out →
**destination** facility Transfer In. This rule compares **only the middle two** — DTW's own
Transfer In vs. its own Transfer Out, for the same `(ref_order_id, item)` — and ignores what the
origin shipped and what the destination received. That's a deliberate scope decision: the other
two legs are a different, already-covered question (XFER-02 covers what was picked at the origin
not being on the TO; XFER-05 covers what was received at the destination not being on the TO).
This rule is specifically about whether the **warehouse's own bookkeeping** balances.

### Correction #1 — most "digital transfer warehouse" activity isn't part of this pattern at all

A naive version of this query (compare DTW In vs DTW Out for every item, no other filter) found
**3,616,977** "left DTW, never arrived" cases all-time — which turned out to be almost entirely
false alarms. Checked live: those items have **no non-DTW origin leg at all** for the same
`(ref_order_id, item)` — DTW isn't a staging waypoint for them, it's acting as its **own
originating warehouse** for a completely different flow (retail/Pantry-bound digital fulfillment).
**Fix:** require a real, non-DTW `Transfer Out` to exist for the same order + item before this
rule even looks at it — i.e. confirm "there's a starting warehouse" first. That dropped the
false-alarm population from 3.6M to **35,230** all-time (and further, once Correction #2 below is
applied, to a number consistent with the table above).

### Correction #2 — the same `ims_sku` suffix bug from XFER-05, recurring inside DTW itself

Even after Correction #1, the "arrived at DTW, never left" bucket was still enormous — **64,863**
in a 30-day/3-day-aged window, and it barely shrank with longer aging (still 20,413 at 21 days),
which doesn't behave like a real backlog. Investigated a sample of 200: **~85%** had a matching
`Transfer Out` at DTW under a **suffixed variant of the same `ims_sku`** (e.g. `Transfer In` posts
as `4200785-25`, `Transfer Out` posts as the bare `4200785`, or vice versa) — the identical
"-N case-multiplier suffix" issue already documented on XFER-05, just occurring on DTW's own two
legs instead of DTW-vs-TO-table. **Fix:** normalize both legs to a base sku
(`REGEXP_REPLACE(ims_sku, r'-[0-9]+$', '')`) before comparing. This is a safe within-order strip
here (unlike XFER-02's TO-table case) — checked and confirmed each `(ref_order_id, base_sku)` has
at most a small number of distinct suffixed variants, not the kind of fan-out that broke XFER-02's
attempt at the same fix — but this is exactly the kind of assumption a data engineer should
double-check before this goes live. Applying it dropped "arrived, never left" from 64,863 to
**5,404** in the same window — an 92% reduction, and a number that finally looks like a real,
believable backlog rather than a data-matching artifact.

### Open questions for the data engineer (this is why it's not live)

1. Is the suffix-normalization assumption in Correction #2 actually correct and exhaustive — are
   there other id-format quirks between DTW's two legs we haven't hit yet?
2. Is "requires a real non-DTW origin `Transfer Out` leg" (Correction #1) the right way to isolate
   genuine 4-leg staged transfers from the digital-fulfillment population, or is there a cleaner
   signal (a flag, a different `ref_order_type`, something else)?
3. Is a 3-day aging window the right cutoff before flagging "stuck" / "left without arriving"? (Not
   deeply calibrated yet — chosen because normal DTW transit time for *balanced* pairs is 0-2 days
   in the vast majority of cases.)
4. **Phase 2, not designed yet:** what to do about the **79,944** pairs (same 30-day window) where
   *both* legs are present but the quantities don't match — a magnitude/percentage question,
   deliberately deferred until Phase 1 (existence-only) is confirmed correct.

### The SQL (documented in `reference.py`, not wired to a live finder)

```sql
-- Catalog rule (framework TWH-01) — DRAFTED, NOT LIVE, pending data-engineer confirmation.
-- Compares ONLY the two ledger legs recorded AT the Digital Transfer Warehouse itself
-- (Transfer In = arrived; Transfer Out = left) for the same (ref_order_id, item) — deliberately
-- ignoring the origin and destination facilities' own legs. Requires a real non-DTW origin
-- 'Transfer Out' leg to exist first (excludes the ~3.6M pure digital-fulfillment DTW-as-source
-- population that never has a matching origin leg and isn't part of this pattern at all).
-- ims_sku is compared suffix-normalized (strip a trailing '-N') — the exact-vs-suffixed id
-- mismatch already found on XFER-05 recurs here between the DTW In and Out legs themselves.
-- Phase 1 (this query): existence-only — flags an item present on one DTW leg but completely
-- absent from the other. Phase 2 (not designed yet): both legs present but quantities differ
-- by more than X% — deferred pending Phase 1 sign-off.
WITH dtw AS (
  SELECT
    ref_order_id,
    REGEXP_REPLACE(ims_sku, r'-[0-9]+$', '')                            AS base_sku,
    SUM(IF(l2_action = 'Transfer In', consumable_quantity_change, 0))   AS dtw_in,
    SUM(IF(l2_action = 'Transfer Out', -consumable_quantity_change, 0)) AS dtw_out,
    MAX(DATE(datetime_utc))                                             AS last_activity
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE system_of_origin = 'digital_transfer_warehouse'
    AND ref_order_type = 'Transfer Order'
    AND l2_action IN ('Transfer In', 'Transfer Out')
    AND ref_order_id IS NOT NULL
    AND ims_sku IS NOT NULL
  GROUP BY ref_order_id, base_sku
),

origin AS (   -- confirms a real non-DTW starting-warehouse leg exists for this order + item
  SELECT DISTINCT
    ref_order_id,
    REGEXP_REPLACE(ims_sku, r'-[0-9]+$', '') AS base_sku
  FROM `wonder-dw-prod-brd.inventory.consolidated_inventory_ledger`
  WHERE system_of_origin != 'digital_transfer_warehouse'
    AND ref_order_type = 'Transfer Order'
    AND l2_action = 'Transfer Out'
    AND ref_order_id IS NOT NULL
    AND ims_sku IS NOT NULL
)

SELECT
  dtw.ref_order_id,
  dtw.base_sku,
  dtw.dtw_in,
  dtw.dtw_out,
  IF(dtw.dtw_in > 0, 'STUCK_AT_WAREHOUSE', 'LEFT_WITHOUT_ARRIVING') AS failure_mode
FROM dtw
JOIN origin USING (ref_order_id, base_sku)
WHERE (dtw.dtw_in > 0) != (dtw.dtw_out > 0)   -- exactly one side present
  AND dtw.last_activity < DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
```

### Tables & columns used

**Table:** Inventory Ledger (`consolidated_inventory_ledger`) only — no PO/TO table join.

| Column | Plain meaning | Role in this rule |
|---|---|---|
| `system_of_origin` | Which system produced the row. | **Scope filter** — `'digital_transfer_warehouse'` for the two legs being compared; `!=` that for confirming a real origin leg exists. |
| `ref_order_type`, `ref_order_id` | Transfer-order tag and id. | Filter + join key. |
| `l2_action` | `'Transfer In'` (arrived) vs `'Transfer Out'` (left). | **The two legs being compared.** |
| `ims_sku` | Raw item id — sometimes suffixed with `-N`. | **Join key, suffix-normalized** — see Correction #2. |
| `consumable_quantity_change` | Signed quantity. | Summed per leg to get `dtw_in` / `dtw_out`. |
| `datetime_utc` | When the movement happened. | **Aging** — `last_activity` vs. the 3-day floor. |

### Example (drafted, from live data)

**Arrived at DTW, never left** — `PO-410376`, Veggie Burger Patty FZN (5 ea): 5 units arrived at
DTW from DISH on 2026-07-28, no matching `Transfer Out` since. `PO-429986`, Lime Juice (32 fl oz):
907 units arrived from DISH on 2026-08-10, still sitting.

**Left DTW, never arrived** — `PO-416356`, Diet Dr. Pepper (12 can): 36 units left DTW on
2026-08-03 (originated at Shawnee) with no matching `Transfer In` ever recorded. `PO-422761`,
Jarritos Lime Soda (24 ea): same pattern, originated at Shawnee, left DTW 2026-08-06.

---

<!-- ───────────────────────────────────────────────────────────────────────────
     REMAINING RULES — to be authored. Each follows the identical six-part structure.
     ─────────────────────────────────────────────────────────────────────────── -->

## Coverage tracker — all rules

Where each rule stands, and whether it's been written up in this guide yet.

**Status legend:** 🟢 **Live** = enabled *and* its detection query is wired in, so it runs daily and
creates tickets · 🟡 **Catalog-only** = enabled but no detection query is wired yet, so it silently
finds nothing · ⚪ **Paused** = query exists but the rule is toggled off · 🔵 **Drafted, not live** =
query written and validated against live data, documented here in full, but deliberately not
enabled and not wired into any finder — waiting on a specific person's confirmation before going
further.

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
| TWH-01 | Transfer Warehouse In/Out Balance | 🔵 Drafted, not live — pending data-engineer confirmation | ✅ |
| XFER-01 | Transfer Order Missing | 🟢 Live | ✅ |
| XFER-02 | SKU Not on Transfer Order | 🟢 Live | ✅ |
| XFER-04 | Transfer Order No Pick Activity | 🟢 Live | ✅ |
| XFER-05 | Received SKU Not on Transfer Order | 🟢 Live | ✅ |
| XFER-07 | Transfer Picked — Not Received | 🟢 Live | ✅ |
| COMPLETE-02 | Negative On-Hand | 🟡 Catalog-only (needs cumulative cross-day balance) | — (catalog) |
| WASTE-DAILY | Daily Waste (Facility) | 🟢 Live | ◻ to do |
| ADJ-DAILY | Daily Adjustments (Facility) | 🟢 Live | ◻ to do |
| COST-01 | Waste SKU Without Cost | 🟢 Live | ✅ |
| COST-02 | Consumable Missing Cost | 🟢 Live | ✅ |

The PO family, **XFER-01**, **XFER-02**, **XFER-04**, **XFER-05**, **XFER-07**, **TWH-01**
(drafted, not live), and both cost rules are fully documented above. Still **to do** (live,
not yet written up): the two daily facility-dollar rules — **WASTE-DAILY** and **ADJ-DAILY**. The
**catalog-only** rules (PO-02, COMPLETE-02) will be written up when their detectors are wired.
