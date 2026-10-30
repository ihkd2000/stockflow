# StockFlow

A small, production-minded inventory operations application for warehouses. Built with **Python, FastAPI, SQLite, and a responsive browser UI**. It is a real application starter, not a pre-scripted AI benchmark. All records are about products, warehouse locations, and inventory movements; **no user accounts or personal/customer information** are collected.

## Getting started

Python 3.10+ required. From the project root:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m uvicorn stockflow.api:app --reload
```

Open http://127.0.0.1:8000 for the dashboard, or http://127.0.0.1:8000/docs for interactive API documentation.

Run tests:

```bash
python -m pytest -q
```

On Windows PowerShell, use double quotes for the editable extras install: `python -m pip install -e ".[dev]"`.

Data defaults to `~/.stockflow/inventory.sqlite3`. Set `STOCKFLOW_DB` to change that location. This project creates the DB automatically on startup.

## Features

- Catalog of products with unique SKUs, category, and per-location reorder threshold.
- Multiple warehouse locations and per-warehouse stock balances.
- Receive, issue, signed adjustment and atomic transfer operations.
- Disallow issuing more stock than is available.
- Immutable activity ledger with transfer pairing and UTC timestamps.
- Optional `Idempotency-Key` header for safe retry of stock operations.
- Dashboard with inventory, reorder alerts, and movement activity.
- Automated tests for key domain rules and database transaction behaviors.

## Example workflow

1. Add warehouses `EAST` and `WEST`.
2. Add product `PART-101` with reorder point `5`.
3. Receive `20` units into `EAST`.
4. Transfer `8` units to `WEST`.
5. Issue `4` units from `WEST`.
6. Review remaining stock and recent activity.

## Engineering notes

- A stock movement is never updated or deleted; corrections produce new entries.
- Transfers write two movements within one SQLite transaction.
- Write operations use `BEGIN IMMEDIATE`, preventing race conditions between read and write on the same SQLite DB.
- No login/authentication yet. **Run locally or behind trusted access control. Do not expose this starter publicly on the internet.**
- Inventory uses integer unit counts; fractional quantities, cost accounting, lot tracking, and ordering have not been implemented.
- `reorder_point` is product-wide, applied to each warehouse in the starter.
- Strict production deployments also need migrations, database backups, request tracing, deployment hardening, and access control.

## Potential future development

See `ROADMAP.md` for incremental feature ideas. Each feature can be treated as a standalone engineering change, with its own specification and tests.

## Expanded operations (v0.2)

Run StockFlow in the same style as ThingsExpireTracker:

```powershell
python -m stockflow serve
```

The application now also includes supplier organizations (no individual or customer details), draft-to-open purchase orders, partial receipts, receipt retry protection, inventory reservations, release/fulfillment, and availability accounting. These workflows are exposed both through the browser dashboard and `/docs` REST API. The browser currently supports single-line purchase-order creation; the API supports multiple lines per order. The receiving form is deliberately minimal and uses prompts; a full multi-line purchasing workspace is a future improvement.

**Important:** The reported Django `{% endif %}` error cannot come from this FastAPI project: there are no Django templates in this codebase. If that error still appears, verify which application is running on port 8000 and stop the older server before running StockFlow.

### Engineering boundaries

This is an expanded local starter, not a complete ERP or production-deployable service. It does not yet include valuation, multi-line purchasing UI, user authentication, supplier billing, migration versioning, or multi-worker stress tests. Do not run it on a public network without security hardening. Persistent data is stored outside the extracted project under `~/.stockflow/` by default.

## Cycle counts and inventory reconciliation (v0.3)

Open **Physical stock counts & reconciliation** on the main page, select a warehouse and enter a count reference. StockFlow snapshots every active product's balance in that warehouse (plus inactive products that still have stock). Enter a nonnegative physical quantity for every line and select **Apply reconciliation**. The system posts a distinct `ADJUST` ledger movement for each discrepancy, atomically updating inventory balances. Alternatively, cancel the open count.

- Only one open count is permitted per warehouse.
- Counts preserve snapshot quantities and the last movement ID, rejecting application if any counted SKU has changed since the count was opened (including quantities that later returned to the original value).
- Applying a count requires all lines to be recorded; adjusted quantities cannot undercut existing active reservations.
- Count application and cancellation are atomic and safely repeatable. Closed counts retain their line history and cannot be edited.
- Existing databases are extended with additional tables at startup; previous inventory, receipts, and reservations are retained.

API routes: `GET/POST /api/counts`, `GET /api/counts/{id}/lines`, `PUT /api/counts/{id}/lines/{product_id}`, and `POST /api/counts/{id}/apply` or `/cancel`. Full schemas are at `/docs`.

**Limitations:** cycle counts are intentionally snapshot based and require a restart if relevant stock changes before reconciliation; there is currently no counted-by user attribution or approval workflow, and there is no user authentication. Run this app locally, not on an untrusted network.


## Inventory Risk & Decision Center (v0.3.0)

The risk panel on the dashboard allows configuring **daily demand**, **supplier lead time**, and **safety buffer days** for each product and warehouse. It calculates free stock (`on_hand - active_reservations`), target stock (`ceil(daily_demand * (lead_days + safety_days))`), days of coverage, and a transparent risk status.

- **HIGH:** insufficient stock to cover the supplier lead time; **MODERATE:** lead time covered but buffer not covered; **LOW:** target covered. Unconfigured pairs are explicitly marked **UNCONFIGURED**.
- **Transfer review:** suggests transferring only from another warehouse's free stock above its target (or reorder point if the warehouse has no planning settings).
- **Replenishment review:** indicates the remaining target shortfall for purchasing consideration. Recommendations are **independent options**, not additive orders.
- **No automatic execution:** recommendations do not create transfers, receipts, or purchase orders. Before any actual movement, users must use the existing operation flow, which rechecks stock and reservation constraints.

API: `PUT /api/risk-policies` and `GET /api/inventory-risks`. See `/docs` for request schemas.

**Scope / limitations:** demand is manually configured (not learned from movements), is assumed constant, and inbound purchase orders are deliberately excluded because the current schema does not store confirmed delivery dates. No supplier optimization, delivery guarantee, forecasting confidence, or pending-receipt deduction is implied. This release is a planning aid rather than a verified forecast.

Run `python -m pytest -q` for regression tests.
