"""Sales order lifecycle with allocation and atomic partial fulfillment."""
import json
import sqlite3
from .db import connect
from .service import DomainError, _change, require_active_product
from .commerce import _available


def create(number, warehouse_id, lines):
    number = number.strip().upper()
    if not number or not lines or len({l['product_id'] for l in lines}) != len(lines) or any(l['quantity'] <= 0 for l in lines):
        raise DomainError('Order number and unique positive-quantity lines required')
    try:
        with connect(write=True) as db:
            if not db.execute('SELECT 1 FROM warehouses WHERE id=?', (warehouse_id,)).fetchone():
                raise DomainError('Unknown warehouse', 404)
            for line in lines:
                require_active_product(db, line['product_id'])
            c = db.execute('INSERT INTO sales_orders(number,warehouse_id) VALUES (?,?)', (number,warehouse_id))
            oid = c.lastrowid
            for line in lines:
                db.execute('INSERT INTO sales_order_lines(order_id,product_id,ordered) VALUES (?,?,?)', (oid,line['product_id'],line['quantity']))
            return detail(oid, db)
    except sqlite3.IntegrityError as e:
        raise DomainError('Sales order number already exists',409) from e


def detail(oid, db=None):
    if db is None:
        with connect() as connection:
            return detail(oid, connection)
    order = db.execute('SELECT o.*,w.code warehouse FROM sales_orders o JOIN warehouses w ON w.id=o.warehouse_id WHERE o.id=?',(oid,)).fetchone()
    if order is None:
        raise DomainError('Unknown sales order',404)
    result = dict(order)
    result['lines'] = [dict(x) for x in db.execute('''SELECT l.*,p.sku FROM sales_order_lines l JOIN products p ON p.id=l.product_id WHERE l.order_id=? ORDER BY l.id''',(oid,))]
    return result


def list_orders():
    with connect() as db:
        return [dict(x) for x in db.execute('SELECT o.*,w.code warehouse FROM sales_orders o JOIN warehouses w ON w.id=o.warehouse_id ORDER BY o.id DESC')]


def edit(oid, lines):
    if not lines or len({l['product_id'] for l in lines}) != len(lines) or any(l['quantity']<=0 for l in lines):
        raise DomainError('Unique products and positive quantities required')
    with connect(write=True) as db:
        current=detail(oid,db)
        if current['status']!='DRAFT':
            raise DomainError('Only draft orders can be edited',409)
        for item in lines:
            require_active_product(db,item['product_id'])
        db.execute('DELETE FROM sales_order_lines WHERE order_id=?',(oid,))
        for item in lines:
            db.execute('INSERT INTO sales_order_lines(order_id,product_id,ordered) VALUES (?,?,?)',(oid,item['product_id'],item['quantity']))
        return detail(oid,db)


def transition(oid, action):
    with connect(write=True) as db:
        order=detail(oid,db)
        if action=='confirm':
            if order['status']!='DRAFT':
                raise DomainError('Only drafts can be confirmed',409)
            db.execute("UPDATE sales_orders SET status='CONFIRMED' WHERE id=?",(oid,))
        elif action=='cancel':
            if order['status'] in ('FULFILLED','CANCELLED'):
                raise DomainError('Order cannot be cancelled',409)
            for line in order['lines']:
                if line['reservation_id']:
                    db.execute("UPDATE reservations SET status='RELEASED' WHERE id=? AND status='ACTIVE'",(line['reservation_id'],))
                db.execute('UPDATE sales_order_lines SET allocated=0 WHERE id=?',(line['id'],))
            db.execute("UPDATE sales_orders SET status='CANCELLED' WHERE id=?",(oid,))
        else:
            raise DomainError('Invalid transition')
        return detail(oid,db)


def allocate(oid):
    """All-or-nothing allocation of outstanding order quantities."""
    with connect(write=True) as db:
        order=detail(oid,db)
        if order['status'] not in ('CONFIRMED','PARTIAL'):
            raise DomainError('Order is not eligible for allocation',409)
        for line in order['lines']:
            missing=line['ordered']-line['fulfilled']-line['allocated']
            if missing<=0:
                continue
            require_active_product(db,line['product_id'])
            if _available(db,line['product_id'],order['warehouse_id'])['available']<missing:
                raise DomainError('Insufficient available stock for full allocation',409)
            if line['reservation_id']:
                db.execute("UPDATE reservations SET quantity=quantity+? WHERE id=? AND status='ACTIVE'",(missing,line['reservation_id']))
            else:
                cur=db.execute('INSERT INTO reservations(reference,product_id,warehouse_id,quantity) VALUES (?,?,?,?)',
                    (f"SALES:{oid}:{line['id']}",line['product_id'],order['warehouse_id'],missing))
                db.execute('UPDATE sales_order_lines SET reservation_id=? WHERE id=?',(cur.lastrowid,line['id']))
            db.execute('UPDATE sales_order_lines SET allocated=allocated+? WHERE id=?',(missing,line['id']))
        return detail(oid,db)


def fulfill(oid, line_id, quantity, key):
    if quantity<=0 or not key.strip():
        raise DomainError('Positive quantity and idempotency key required')
    with connect(write=True) as db:
        existing=db.execute('SELECT * FROM sales_fulfillment_keys WHERE key=?',(key,)).fetchone()
        if existing:
            if (existing['order_id'],existing['line_id'],existing['quantity'])!=(oid,line_id,quantity):
                raise DomainError('Idempotency key already used for another request',409)
            return json.loads(existing['result_json'])
        order=detail(oid,db)
        if order['status'] not in ('CONFIRMED','PARTIAL'):
            raise DomainError('Order cannot be fulfilled',409)
        line=next((l for l in order['lines'] if l['id']==line_id),None)
        if line is None:
            raise DomainError('Line not found in order',404)
        if quantity>line['allocated']:
            raise DomainError('Fulfillment exceeds allocated stock',409)
        reserved=db.execute('SELECT * FROM reservations WHERE id=? AND status=\'ACTIVE\'',(line['reservation_id'],)).fetchone()
        if reserved is None or reserved['quantity']!=line['allocated']:
            raise DomainError('Sales allocation is inconsistent',409)
        _change(db,line['product_id'],order['warehouse_id'],-quantity,'ISSUE',f"SO:{order['number']}:LINE:{line_id}")
        left=line['allocated']-quantity
        if left:
            db.execute('UPDATE reservations SET quantity=? WHERE id=?',(left,line['reservation_id']))
        else:
            db.execute("UPDATE reservations SET status='FULFILLED' WHERE id=?",(line['reservation_id'],))
            db.execute('UPDATE sales_order_lines SET reservation_id=NULL WHERE id=?',(line_id,))
        db.execute('UPDATE sales_order_lines SET fulfilled=fulfilled+?,allocated=allocated-? WHERE id=?',(quantity,quantity,line_id))
        remaining=db.execute('SELECT SUM(ordered-fulfilled) FROM sales_order_lines WHERE order_id=?',(oid,)).fetchone()[0]
        db.execute('UPDATE sales_orders SET status=? WHERE id=?',('FULFILLED' if remaining==0 else 'PARTIAL',oid))
        result=detail(oid,db)
        db.execute('INSERT INTO sales_fulfillment_keys(key,order_id,line_id,quantity,result_json) VALUES(?,?,?,?,?)',(key,oid,line_id,quantity,json.dumps(result)))
        return result
