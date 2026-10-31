# StockFlow — extension roadmap

Keep each feature as a realistic business request. Existing receiving, issuing, transfers, idempotency, and audit history must continue to work.

1. **Purchase orders and partial receiving.** Create draft/approved/partially received/received/cancelled orders for organizational suppliers. Support partial deliveries, backorders, cancellation rules, and prevention of receiving beyond the ordered amount. No personal contact data.
2. **Reservations and allocation.** Reserve on-hand inventory for work orders. Track available vs. reserved; enforce allocation at transaction boundaries; release on cancellation or expiry. Transfers and adjustments must respect reservations.
3. **Batch and lot traceability.** Track a lot number, expiration date, and location on receipts. Implement FIFO or FEFO picking; block expired lots; preserve provenance through transfers and returns.
4. **Stock counting and reconciliation.** Create count sessions, freeze/soft-freeze rules, handle counted variances, require review before posting, and guard concurrent stock changes.
5. **Replenishment planning.** Per-warehouse reorder policies, lead times, demand history, order suggestions, and constraint-aware redistribution among warehouses.
6. **Returns and reverse logistics.** Link item returns to a previous issue, quarantine defective goods, and prevent returning more than originally issued.
7. **Durable outbox for events.** Emit movement events with exactly-once business effects despite at-least-once delivery and process crashes; implement retry and dead-letter handling.
8. **Accounting / invoicing module.** Add organizational buyers, invoices, credit notes, currency, tax configurations, and immutable posted documents. Keep monetary rounding and inventory issuance consistent without recording personal identifiers.

## Quality goals for each increment

- Migration works against existing databases and preserves the stock ledger.
- API and UI agree on validation and state transitions.
- Tests cover happy paths, rejected operations, retries, concurrent modifications, and upgrades.
- Rollback on failure never leaves an incomplete multi-step transaction.
- Existing workflows remain compatible, and documentation stays accurate.

### Completed in v0.3
- Physical cycle counts per warehouse with product-by-product entries, variance review, and atomic ledger reconciliation.
- Stale snapshot detection, reserved-stock constraints, safe retry and cancellation, regression tests.

### Proposed follow-on work
- Multi-page dashboard/navigation and searchable, editable product/warehouse views.
- Scoped cycle counts, blind counting, variance approval, and multi-pass recount workflows.
- Purchase-order editing, receiving discrepancies, and supplier returns.
- Sales orders and fulfillment with inventory allocation.


### Completed — Inventory Risk & Decision Center (0.3.0)
- Per-warehouse demand, lead time and safety buffer policies
- Explainable shortage risk, coverage and shortfall calculations
- Non-mutating transfer and replenishment review suggestions
- API and browser panel with regression tests

### Potential future work
- Dedicated multi-page navigation and reporting
- Confirmed expected-delivery dates and time-phased inbound supply
- Demand estimation using historical issues (excluding transfers and adjustments)
- Proposal preview and revalidation with explicit human approval
- Cross-warehouse cost/lead-time optimization and demand variability

- [x] Separate existing workflows into navigable views (v0.4.0).
- [ ] Add searchable product and warehouse listings, with edit and deactivation operations.

- [x] Advanced product catalog management: search, pagination, editing, safe deactivation, details, CSV export (v0.5.0)
