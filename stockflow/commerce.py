"""Purchasing and reservation workflows built on inventory's atomic ledger."""
import sqlite3
import json
from .db import connect
from .service import DomainError, _exists, _change


def list_rows(sql, args=()):
    with connect() as db:
        return [dict(r) for r in db.execute(sql, args)]


def supplier(code, organization_name):
    if not code.strip() or not organization_name.strip():
        raise DomainError('Supplier code and organization name required')
    try:
        with connect(write=True) as db:
            c = db.execute('INSERT INTO suppliers(code,organization_name) VALUES(?,?)',
                           (code.strip().upper(),organization_name.strip()))
            return dict(db.execute('SELECT * FROM suppliers WHERE id=?',(c.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        raise DomainError('Supplier code already exists',409)


def create_order(number, supplier_id, warehouse_id, lines):
    if not number.strip() or not lines:
        raise DomainError('Order number and lines required')
    ids = [x['product_id'] for x in lines]
    if len(ids)!=len(set(ids)) or any(x['quantity']<=0 for x in lines):
        raise DomainError('Positive quantities and unique products required')
    try:
        with connect(write=True) as db:
            _exists(db,'suppliers',supplier_id)
            _exists(db,'warehouses',warehouse_id)
            for pid in ids:
                _exists(db,'products',pid)
            c = db.execute('INSERT INTO purchase_orders(number,supplier_id,warehouse_id) VALUES(?,?,?)',
                           (number.strip().upper(),supplier_id,warehouse_id))
            for line in lines:
                db.execute('INSERT INTO purchase_order_lines(order_id,product_id,ordered) VALUES(?,?,?)',
                           (c.lastrowid,line['product_id'],line['quantity']))
            return {'id':c.lastrowid,'number':number.strip().upper(),'status':'DRAFT'}
    except sqlite3.IntegrityError as e:
        raise DomainError('Duplicate purchase order',409) from e


def change_order_status(order_id, action):
    allowed = {'submit':('DRAFT','OPEN'), 'cancel':('DRAFT','CANCELLED')}
    if action not in allowed:
        raise DomainError('Unknown transition')
    expected,new = allowed[action]
    with connect(write=True) as db:
        c = db.execute('UPDATE purchase_orders SET status=? WHERE id=? AND status=?', (new,order_id,expected))
        if not c.rowcount:
            raise DomainError('Order not found or transition not permitted',409)
        return {'id':order_id,'status':new}


def receive_line(order_id,line_id,quantity,key):
    if quantity<=0 or not key or not key.strip():
        raise DomainError('Quantity must be positive and receipt idempotency key required')
    with connect(write=True) as db:
        old=db.execute('SELECT * FROM receipt_keys WHERE key=?',(key,)).fetchone()
        if old:
            if old['line_id']!=line_id or old['quantity']!=quantity:
                raise DomainError('Receipt key reused for different request',409)
            return json.loads(old['receipt_json'])
        row=db.execute('''SELECT l.*,o.status,o.warehouse_id,o.number FROM purchase_order_lines l
            JOIN purchase_orders o ON o.id=l.order_id WHERE l.id=? AND o.id=?''',(line_id,order_id)).fetchone()
        if not row:
            raise DomainError('Unknown order line',404)
        if row['status'] not in ('OPEN','PARTIAL'):
            raise DomainError('Order is not receivable',409)
        if row['received']+quantity>row['ordered']:
            raise DomainError('Receipt exceeds outstanding quantity',409)
        _change(db,row['product_id'],row['warehouse_id'],quantity,'RECEIVE',f"PO:{row['number']}:LINE:{line_id}")
        db.execute('UPDATE purchase_order_lines SET received=received+? WHERE id=?',(quantity,line_id))
        outstanding=db.execute('SELECT SUM(ordered-received) FROM purchase_order_lines WHERE order_id=?',(order_id,)).fetchone()[0]
        status='RECEIVED' if outstanding==0 else 'PARTIAL'
        db.execute('UPDATE purchase_orders SET status=? WHERE id=?',(status,order_id))
        result={'order_id':order_id,'line_id':line_id,'received':quantity,'outstanding':outstanding,'status':status}
        db.execute('INSERT INTO receipt_keys(key,line_id,quantity,receipt_json) VALUES(?,?,?,?)',
                   (key,line_id,quantity,json.dumps(result)))
        return result


def _available(db,product_id,warehouse_id):
    r=db.execute('SELECT quantity FROM balances WHERE product_id=? AND warehouse_id=?',(product_id,warehouse_id)).fetchone()
    on_hand=r['quantity'] if r else 0
    reserved=db.execute('''SELECT COALESCE(SUM(quantity),0) FROM reservations
      WHERE product_id=? AND warehouse_id=? AND status='ACTIVE' ''',(product_id,warehouse_id)).fetchone()[0]
    return {'on_hand':on_hand,'reserved':reserved,'available':on_hand-reserved}


def reserve(reference,product_id,warehouse_id,quantity):
    if not reference.strip() or quantity<=0:
        raise DomainError('Reference and positive quantity required')
    with connect(write=True) as db:
        _exists(db,'products',product_id)
        _exists(db,'warehouses',warehouse_id)
        prior=db.execute('SELECT * FROM reservations WHERE reference=?',(reference,)).fetchone()
        if prior:
            raise DomainError('Reservation reference already exists',409)
        if _available(db,product_id,warehouse_id)['available']<quantity:
            raise DomainError('Insufficient available (unreserved) stock',409)
        c=db.execute('INSERT INTO reservations(reference,product_id,warehouse_id,quantity) VALUES(?,?,?,?)',
                     (reference,product_id,warehouse_id,quantity))
        return dict(db.execute('SELECT * FROM reservations WHERE id=?',(c.lastrowid,)).fetchone())


def finalize_reservation(reservation_id,action):
    if action not in ('release','fulfill'):
        raise DomainError('Unknown reservation transition')
    with connect(write=True) as db:
        row=db.execute('SELECT * FROM reservations WHERE id=?',(reservation_id,)).fetchone()
        if not row:
            raise DomainError('Reservation not found',404)
        if row['status']!='ACTIVE':
            raise DomainError('Reservation is already finalized',409)
        if action=='fulfill':
            _change(db,row['product_id'],row['warehouse_id'],-row['quantity'],
                    'ISSUE',f"RESERVATION:{row['reference']}")
        status='FULFILLED' if action=='fulfill' else 'RELEASED'
        db.execute('UPDATE reservations SET status=? WHERE id=?',(status,reservation_id))
        return {'id':reservation_id,'status':status}