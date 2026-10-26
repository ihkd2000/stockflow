import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = str(Path.home() / '.stockflow' / 'inventory.sqlite3')


def db_path():
    return os.environ.get('STOCKFLOW_DB', DEFAULT_DB)


@contextmanager
def connect(write=False):
    path = db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    try:
        if write:
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect(write=True) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'General',
            reorder_point INTEGER NOT NULL DEFAULT 0 CHECK(reorder_point >= 0),
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS warehouses (
            id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS balances (
            product_id INTEGER NOT NULL REFERENCES products(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
            PRIMARY KEY(product_id, warehouse_id)
        );
        CREATE TABLE IF NOT EXISTS movements (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            action TEXT NOT NULL CHECK(action IN ('RECEIVE','ISSUE','TRANSFER_OUT','TRANSFER_IN','ADJUST')),
            product_id INTEGER NOT NULL REFERENCES products(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            delta INTEGER NOT NULL CHECK(delta != 0), reference TEXT NOT NULL DEFAULT '',
            transfer_group TEXT
        );
        CREATE TABLE IF NOT EXISTS operations (
            idempotency_key TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
            result_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_movements_product ON movements(product_id, created_at);
        ''')


def init_commerce_db():
    """Add purchasing and stock allocations without discarding existing data."""
    with connect(write=True) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
            organization_name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY, number TEXT NOT NULL UNIQUE,
            supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            status TEXT NOT NULL DEFAULT 'DRAFT'
              CHECK(status IN ('DRAFT','OPEN','PARTIAL','RECEIVED','CANCELLED')),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE TABLE IF NOT EXISTS purchase_order_lines (
            id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES purchase_orders(id),
            product_id INTEGER NOT NULL REFERENCES products(id),
            ordered INTEGER NOT NULL CHECK(ordered>0),
            received INTEGER NOT NULL DEFAULT 0 CHECK(received>=0 AND received<=ordered),
            UNIQUE(order_id, product_id)
        );
        CREATE TABLE IF NOT EXISTS receipt_keys (
            key TEXT PRIMARY KEY, line_id INTEGER NOT NULL REFERENCES purchase_order_lines(id),
            quantity INTEGER NOT NULL, receipt_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY, reference TEXT NOT NULL UNIQUE,
            product_id INTEGER NOT NULL REFERENCES products(id),
            warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
            quantity INTEGER NOT NULL CHECK(quantity>0),
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','RELEASED','FULFILLED')),
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_reservations_stock
          ON reservations(product_id,warehouse_id,status);
        ''')