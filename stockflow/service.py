"""Stock operations: atomic balances, immutable movement history, replay protection."""
import hashlib
import json
import sqlite3
import uuid
from .db import connect


class DomainError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def rows(query, params=()):
    with connect() as db:
        return [dict(r) for r in db.execute(query, params)]


def add_product(sku, name, category, reorder_point):
    sku, name, category = sku.strip().upper(), name.strip(), category.strip()
    if not sku or not name or reorder_point < 0:
        raise DomainError('SKU and name are required; reorder point must be nonnegative')
    try:
        with connect(write=True) as db:
            cur = db.execute('INSERT INTO products(sku,name,category,reorder_point) VALUES(?,?,?,?)',
                             (sku, name, category or 'General', reorder_point))
            return dict(db.execute('SELECT * FROM products WHERE id=?', (cur.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        raise DomainError('SKU already exists', 409)


def add_warehouse(code, name):
    code, name = code.strip().upper(), name.strip()
    if not code or not name:
        raise DomainError('Warehouse code and name are required')
    try:
        with connect(write=True) as db:
            cur = db.execute('INSERT INTO warehouses(code,name) VALUES(?,?)', (code, name))
            return dict(db.execute('SELECT * FROM warehouses WHERE id=?', (cur.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        raise DomainError('Warehouse code already exists', 409)


def _exists(db, table, id):
    if not db.execute(f'SELECT 1 FROM {table} WHERE id=?', (id,)).fetchone():
        raise DomainError(f'Unknown {table[:-1]} ID: {id}', 404)


def _change(db, product_id, warehouse_id, delta, action, reference, group=None):
    db.execute('INSERT OR IGNORE INTO balances(product_id,warehouse_id,quantity) VALUES(?,?,0)',
               (product_id, warehouse_id))
    cur = db.execute('UPDATE balances SET quantity=quantity+? WHERE product_id=? AND warehouse_id=? AND quantity+?>=0',
                     (delta, product_id, warehouse_id, delta))
    if cur.rowcount != 1:
        raise DomainError('Insufficient stock; operation rejected', 409)
    db.execute('INSERT INTO movements(action,product_id,warehouse_id,delta,reference,transfer_group) VALUES(?,?,?,?,?,?)',
               (action, product_id, warehouse_id, delta, reference, group))


def operate(kind, product_id, quantity, warehouse_id, target_warehouse_id=None, reference='', key=None):
    if kind not in ('RECEIVE', 'ISSUE', 'TRANSFER', 'ADJUST'):
        raise DomainError('Unknown operation')
    if quantity <= 0 and kind != 'ADJUST':
        raise DomainError('Quantity must be positive')
    if kind == 'ADJUST' and quantity == 0:
        raise DomainError('Adjustment cannot be zero')
    if kind == 'TRANSFER' and (target_warehouse_id is None or target_warehouse_id == warehouse_id):
        raise DomainError('Transfer requires a different destination warehouse')
    if key is not None and not key.strip():
        raise DomainError('Idempotency key cannot be blank')
    payload = dict(kind=kind, product_id=product_id, quantity=quantity, warehouse_id=warehouse_id,
                   target_warehouse_id=target_warehouse_id, reference=reference)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with connect(write=True) as db:
        if key:
            existing = db.execute('SELECT * FROM operations WHERE idempotency_key=?', (key,)).fetchone()
            if existing:
                if existing['request_hash'] != digest:
                    raise DomainError('Idempotency key was already used for a different operation', 409)
                return json.loads(existing['result_json'])
        _exists(db, 'products', product_id)
        _exists(db, 'warehouses', warehouse_id)
        if kind in ('ISSUE', 'TRANSFER') or (kind == 'ADJUST' and quantity < 0):
            current = db.execute('SELECT quantity FROM balances WHERE product_id=? AND warehouse_id=?', (product_id, warehouse_id)).fetchone()
            locked = db.execute("SELECT COALESCE(SUM(quantity),0) FROM reservations WHERE product_id=? AND warehouse_id=? AND status='ACTIVE'", (product_id,warehouse_id)).fetchone()[0]
            delta = quantity if kind == 'ADJUST' else -quantity
            if (current['quantity'] if current else 0) + delta < locked:
                raise DomainError('Operation would consume reserved stock',409)
        if kind == 'TRANSFER':
            _exists(db, 'warehouses', target_warehouse_id)
            group = str(uuid.uuid4())
            _change(db, product_id, warehouse_id, -quantity, 'TRANSFER_OUT', reference, group)
            _change(db, product_id, target_warehouse_id, quantity, 'TRANSFER_IN', reference, group)
        else:
            delta = quantity if kind in ('RECEIVE', 'ADJUST') else -quantity
            _change(db, product_id, warehouse_id, delta, kind, reference)
        current = db.execute('SELECT quantity FROM balances WHERE product_id=? AND warehouse_id=?',
                             (product_id, warehouse_id)).fetchone()['quantity']
        result = {'status': 'applied', 'kind': kind, 'product_id': product_id,
                  'warehouse_id': warehouse_id, 'current_quantity': current}
        if key:
            db.execute('INSERT INTO operations VALUES(?,?,?)', (key, digest, json.dumps(result)))
        return result