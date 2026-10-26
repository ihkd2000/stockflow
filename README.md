# StockFlow

A small, production-minded inventory operations application for warehouses. Built with **Python, FastAPI, SQLite, and a responsive browser UI**. All records are about products, warehouse locations, and inventory movements.

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
