# Real BigQuery schema — mapping notes (2026-06-09 handoff)

Project `wonder-dw-prod-brd`, dataset `inventory`.
- Ledger: `consolidated_inventory_ledger`
- PO table: `int_ledger_purchase_orders`

The fixture/engine logic was written against a simplified schema; the real tables are
richer and use different semantics. This is the planned mapping — values marked **(profile)**
need a quick look at the real data (distinct categorical values) before the rule is correct.

## Ledger column mapping (logical → real)

| logical | real column | notes |
|---|---|---|
| row id | `id` | unique surrogate key → ticket/fingerprint row id |
| source-system record id | `record_id` | from upstream system |
| system of origin | `system_of_origin` | Pantry / Ship Hero / Fishbowl **(profile values)** |
| event timestamp | `datetime_utc` (UTC), `datetime_et` | candidate partition / day filter |
| accounting day | `accounting_posted_date` (DATE) | alt "day" for validation (GL relevance) |
| facility | `facility_id` (+ `facility_name`, `facility_type`) | **(profile facility_type incl. Transfer Warehouse)** |
| sku (join key) | `ims_sku` | present in both tables → PO join key; also wonder_sku/vendor_sku/consumable_sku/pack_sku |
| qty change | `quantity_changed` (+ `uom`); also `ims_quantity_change`, `wsku_quantity_change` | which is canonical? **(profile)** |
| PO / order ref | `ref_order_id` (+ `ref_order_type`) | no dedicated po_number; PO receipts identified by `ref_order_type` **(profile values)** |
| action class | `l1_action`, `l2_action`, `raw_action` | Add/Move/Remove/Adjust/Correction vocab **(profile)** |
| correction ref | `correction_ref_id` | |
| lot expiration | `lot_expiration_id` (+ `lot_expiration_date`) | |

## PO table column mapping

| logical | real column | notes |
|---|---|---|
| PO number | `po` (+ `renamed_po`) | join target for ledger `ref_order_id` |
| sku | `ims_sku` | join to ledger `ims_sku`; also wonder_sku/supplier_sku/consumable_sku/pack_sku |
| ordered qty | `ims_sku_qty` (also `wonder_sku_qty`, `supplier_sku_qty`) | |
| received qty | `received_qty` (+ `on_time_receipt_qty`, `late_receipt_qty`) | **PO table already carries received_qty** → over-receipt may not need a ledger join |
| price | `supplier_price` | |
| status | `status` | **(profile values)** for "cancelled/closed" freshness rules |
| supplier | `supplier_id`, `supplier_name` | |
| expected date | `expected_date` | |

## First live rules (matches the transcript priority)

1. **PO-01 NULL PO** — ledger rows that are PO receipts (`ref_order_type` = PO value, **profile**) with `ref_order_id IS NULL`.
2. **PO-02 PO missing** — ledger `ref_order_id` (PO receipts) not present in PO table `po`/`renamed_po`.
3. **PO-03 over-receipt** — PO table `received_qty > ims_sku_qty * (1 + tol)` (single-table; or ledger-join variant per the call).

Deferred until later (need more than one partition / extra design):
- **Negative on-hand** — no `running_on_hand` column; requires cumulative SUM(`quantity_changed`) by item/facility/location across history (window), not a single-day check.
- **Transfer Warehouse imbalance** — needs transfer-order pairing + identifying the Transfer Warehouse via `facility_type`.

## How the engine adapts
Keep the logical engine stable; the **BigQuery adapter** translates real columns → logical
fields, and the first live rules are (re)written against real `ref_order_type` / action values
once profiled. Profiling queries are capped (`maximum_bytes_billed`) and restricted to a single
partition, so there is no risk of an expensive scan.

## Standard cost table (Dynamics ERP) — provided by Pavel 2026-06-11

The authoritative per-item standard cost lives in the ERP (Microsoft Dynamics), project
**`wonder-raw-prod`**, dataset **`erp_prod_batch`** — a *different* project from the
inventory warehouse (`wonder-dw-prod-brd`). Standard costs are effectivity-dated
(`ActivationDate`), so the query keeps only the **latest activated** price per item at the
`'control'` inventory site.

**Returns:** `ITEMID`, `PRICE`, `PRICEUNIT`, `UnitPrice = PRICE/PRICEUNIT`, `UNITID` (UoM).
`UnitPrice` is the per-unit standard cost.

**Intended use** (replaces the current PO-derived `_cost_cte()` placeholder, which is why the
waste $ are off today — e.g. the "half a ton of cheese = $3,700" case):
- **Waste valuation** — value `WASTE_DAILY_FACILITY` net qty at this `UnitPrice` instead of the
  derived cost.
- **#66 rule (`CONSUMABLE_ZERO_COST`)** — `LEFT JOIN` from the ledger to this table; flag log
  items whose `UnitPrice` is 0 / NULL.

**⚠️ Open before wiring in:**
1. The pasted SQL below has copy/paste corruption (the `HAVING` line and the `itemPriceMax`
   subquery alias + join-back are garbled) — **get a clean copy from Pavel** before using.
2. **Join key:** how does ERP `ITEMID` map to our keys (`ims_sku` / `consumable_sku`)? Confirm
   with Pavel/Johnny.
3. **UoM:** `UNITID` here vs `consumable_uom` in the ledger — may need conversion before costing.

Raw SQL as provided (verbatim — corrupted, for reference only):

```sql
SELECT
    inventitemprice.ITEMID,
    PRICE,
    PRICEUNIT,
    PRICE/PRICEUNIT as UnitPrice,
    UNITID
FROM wonder-raw-prod.erp_prod_batch.inventitempriceftistaging AS inventitemprice
INNER JOIN (
    SELECT
        MAX(ActivationDate) AS ActivationDate,
        MAX(inventitemprice.CREATEDTIME) AS CREATEDTIME,
        ITEMID,
        inventitemprice.INVENTDIMID,
        inventitemprice.DATAAREAID
    FROM wonder-raw-prod.erp_prod_batch.inventitempriceftistaging AS inventitemprice
    INNER JOIN wonder-raw-prod.erp_prod_batch.inventdimftistaging AS dim
        ON dim.INVENTDIMID = inventitemprice.INVENTDIMID
        AND LOWER(dim.INVENTDIMDATAAREAID) = LOWER(inventitemprice.DATAAREAID)
        AND LOWER(dim.INVENTSITEID) = 'control'
    GROUP BY
        ITEMID,
        inventitemprice.DATAAREAID,
        inventitemprice.INVENTDIMID
    HAVING LOWER(inventitemprice.DATAAREAIte = inventitemprice.ACTIVATIONDATE
    AND itemPriceMax.CREATEDTIME = inventitemprice.CREATEDTIME
    AND LOWER(itemPriceMax.INVENTDIMID) = LOWER(inventitemprice.INVENTDIMID)
    AND LOWER(itemPriceMax.DATAAREAID) = LOWER(inventitemprice.DATAAREAID)
```

**Intended structure** (reconstructed from the fragments — the bottom `itemPriceMax.*`
conditions are the *outer* join-back, not a `HAVING`): outer `inventitemprice` ⋈ a subquery
aliased `itemPriceMax` that takes `MAX(ActivationDate)`/`MAX(CREATEDTIME)` per
(`ITEMID`, `DATAAREAID`, `INVENTDIMID`) for site `'control'`, joining back on
`ActivationDate = CREATEDTIME = INVENTDIMID = DATAAREAID` to keep only the latest-activated
row. Note the ERP uses `LOWER(...)` on every string join key (case-insensitive) — the same
guard we deferred on the inventory side.
