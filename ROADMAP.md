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
