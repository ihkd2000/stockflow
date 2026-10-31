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
        require_active_product(db, product_id)
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


def _product_filters(search='', category='', status='all'):
    clauses, args = [], []
    if search.strip():
        clauses.append("(sku LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')")
        term = '%' + search.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
        args.extend((term, term))
    if category.strip():
        clauses.append('category = ?')
        args.append(category.strip())
    if status != 'all':
        clauses.append('active = ?')
        args.append(1 if status == 'active' else 0)
    return (' WHERE ' + ' AND '.join(clauses)) if clauses else '', args


def catalog(search='', category='', status='all', sort='sku', descending=False, page=1, page_size=20):
    if status not in ('all','active','inactive') or sort not in ('sku','name','category','reorder_point'):
        raise DomainError('Invalid catalog filter')
    where, args = _product_filters(search, category, status)
    with connect() as db:
        total = db.execute('SELECT COUNT(*) FROM products' + where, args).fetchone()[0]
        data = [dict(r) for r in db.execute('SELECT * FROM products' + where + f' ORDER BY {sort} {"DESC" if descending else "ASC"}, id ASC LIMIT ? OFFSET ?', (*args, page_size, (page-1)*page_size))]
    return {'items': data, 'total': total, 'page': page, 'page_size': page_size, 'pages': max(1,(total+page_size-1)//page_size)}


def catalog_export(search='', category='', status='all'):
    where, args = _product_filters(search, category, status)
    return rows('SELECT sku,name,category,reorder_point,active FROM products' + where + ' ORDER BY sku,id', args)


def update_product(product_id, sku, name, category, reorder_point):
    sku, name, category = sku.strip().upper(), name.strip(), category.strip() or 'General'
    if not sku or not name or reorder_point < 0:
        raise DomainError('SKU and name are required; reorder point must be nonnegative')
    try:
        with connect(write=True) as db:
            _exists(db,'products',product_id)
            db.execute('UPDATE products SET sku=?,name=?,category=?,reorder_point=? WHERE id=?',(sku,name,category,reorder_point,product_id))
            return dict(db.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone())
    except sqlite3.IntegrityError:
        raise DomainError('SKU already exists',409)


def set_product_status(product_id, active):
    with connect(write=True) as db:
        _exists(db,'products',product_id)
        if not active:
            # Preserve existing commitments and prevent a stranded active reservation.
            held = db.execute("SELECT COUNT(*) FROM reservations WHERE product_id=? AND status='ACTIVE'",(product_id,)).fetchone()[0]
            if held:
                raise DomainError('Release or fulfill active reservations before deactivation',409)
            pending = db.execute("SELECT COUNT(*) FROM purchase_order_lines l JOIN purchase_orders o ON o.id=l.order_id WHERE l.product_id=? AND o.status IN ('DRAFT','OPEN','PARTIAL')",(product_id,)).fetchone()[0]
            if pending:
                raise DomainError('Resolve open purchase orders before deactivation',409)
        db.execute('UPDATE products SET active=? WHERE id=?',(int(active),product_id))
        return dict(db.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone())


def product_detail(product_id):
    with connect() as db:
        product = db.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone()
        if not product:
            raise DomainError('Unknown product',404)
        stock = [dict(r) for r in db.execute('''SELECT w.code warehouse,w.name,coalesce(b.quantity,0) on_hand,
            coalesce((SELECT sum(quantity) FROM reservations r WHERE r.product_id=? AND r.warehouse_id=w.id AND r.status='ACTIVE'),0) reserved
            FROM warehouses w LEFT JOIN balances b ON b.warehouse_id=w.id AND b.product_id=? ORDER BY w.code''',(product_id,product_id))]
        movements = [dict(r) for r in db.execute('''SELECT m.created_at,m.action,w.code warehouse,m.delta,m.reference FROM movements m JOIN warehouses w ON w.id=m.warehouse_id WHERE m.product_id=? ORDER BY m.id DESC LIMIT 30''',(product_id,))]
        reservations = [dict(r) for r in db.execute('''SELECT r.reference,w.code warehouse,r.quantity,r.status FROM reservations r JOIN warehouses w ON w.id=r.warehouse_id WHERE r.product_id=? AND r.status='ACTIVE' ORDER BY r.id DESC''',(product_id,))]
    return {'product':dict(product),'stock':stock,'movements':movements,'reservations':reservations}


def require_active_product(db, product_id):
    product = db.execute('SELECT active FROM products WHERE id=?',(product_id,)).fetchone()
    if not product:
        raise DomainError('Unknown product',404)
    if not product['active']:
        raise DomainError('Product is inactive',409)
