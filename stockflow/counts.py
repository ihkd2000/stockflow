"""Physical inventory counts and conservative, atomic reconciliation."""
from .db import connect
from .service import DomainError, _exists, _change


def list_counts():
    with connect() as db:
        return [dict(r) for r in db.execute('''SELECT c.*,w.code warehouse FROM stock_counts c JOIN warehouses w ON w.id=c.warehouse_id ORDER BY c.id DESC''')]


def lines(count_id):
    with connect() as db:
        _get(db, count_id)
        return [dict(r) for r in db.execute('''SELECT l.*,p.sku,p.name FROM stock_count_lines l JOIN products p ON p.id=l.product_id WHERE l.count_id=? ORDER BY p.sku''',(count_id,))]


def _get(db, count_id):
    row=db.execute('SELECT * FROM stock_counts WHERE id=?',(count_id,)).fetchone()
    if row is None:
        raise DomainError('Unknown stock count',404)
    return row


def create(warehouse_id, reference):
    reference=reference.strip()
    if not reference or len(reference)>120:
        raise DomainError('Reference is required (maximum 120 characters)')
    with connect(write=True) as db:
        _exists(db,'warehouses',warehouse_id)
        if db.execute("SELECT 1 FROM stock_counts WHERE warehouse_id=? AND status='OPEN'",(warehouse_id,)).fetchone():
            raise DomainError('An open count already exists for this warehouse',409)
        cur=db.execute('INSERT INTO stock_counts(warehouse_id,reference) VALUES(?,?)',(warehouse_id,reference))
        count_id=cur.lastrowid
        db.execute('''INSERT INTO stock_count_lines(count_id,product_id,expected,last_movement_id)
                      SELECT ?,p.id,COALESCE(b.quantity,0),
                      COALESCE((SELECT MAX(m.id) FROM movements m WHERE m.product_id=p.id AND m.warehouse_id=?),0) FROM products p
                      LEFT JOIN balances b ON b.product_id=p.id AND b.warehouse_id=?
                      WHERE p.active=1 OR COALESCE(b.quantity,0)>0''',(count_id,warehouse_id,warehouse_id))
        if db.execute('SELECT COUNT(*) FROM stock_count_lines WHERE count_id=?',(count_id,)).fetchone()[0]==0:
            raise DomainError('Create at least one product before starting a count',409)
        return {'id':count_id,'warehouse_id':warehouse_id,'reference':reference,'status':'OPEN'}


def record(count_id, product_id, quantity):
    if quantity<0:
        raise DomainError('Counted quantity must be nonnegative')
    with connect(write=True) as db:
        c=_get(db,count_id)
        if c['status']!='OPEN':
            raise DomainError('Count is no longer open',409)
        result=db.execute('UPDATE stock_count_lines SET counted=? WHERE count_id=? AND product_id=?',(quantity,count_id,product_id))
        if result.rowcount!=1:
            raise DomainError('Product is not part of this count',404)
        return {'count_id':count_id,'product_id':product_id,'counted':quantity}


def finalize(count_id, action):
    if action not in ('apply','cancel'):
        raise DomainError('Unknown count action')
    with connect(write=True) as db:
        c=_get(db,count_id)
        target='APPLIED' if action=='apply' else 'CANCELLED'
        if c['status']==target:
            return {'id':count_id,'status':target,'replayed':True}
        if c['status']!='OPEN':
            raise DomainError('Count is already closed',409)
        entries=db.execute('SELECT * FROM stock_count_lines WHERE count_id=?',(count_id,)).fetchall()
        adjustments=0
        if action=='apply':
            if any(line['counted'] is None for line in entries):
                raise DomainError('Every product must be counted before reconciliation',409)
            for line in entries:
                product_id=line['product_id']
                current=db.execute('SELECT quantity FROM balances WHERE warehouse_id=? AND product_id=?',(c['warehouse_id'],product_id)).fetchone()
                on_hand=current['quantity'] if current else 0
                latest_id=db.execute('SELECT COALESCE(MAX(id),0) FROM movements WHERE warehouse_id=? AND product_id=?',(c['warehouse_id'],product_id)).fetchone()[0]
                if on_hand!=line['expected'] or latest_id!=line['last_movement_id']:
                    raise DomainError('Inventory changed since count started. Cancel and start a new count.',409)
                reserved=db.execute("SELECT COALESCE(SUM(quantity),0) FROM reservations WHERE warehouse_id=? AND product_id=? AND status='ACTIVE'",(c['warehouse_id'],product_id)).fetchone()[0]
                if line['counted']<reserved:
                    raise DomainError('Counted stock cannot be less than active reservations',409)
            for line in entries:
                delta=line['counted']-line['expected']
                if delta:
                    _change(db,line['product_id'],c['warehouse_id'],delta,'ADJUST',f"COUNT-{count_id}: {c['reference']}")
                    adjustments+=1
        db.execute("UPDATE stock_counts SET status=?,closed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",(target,count_id))
        return {'id':count_id,'status':target,'adjusted_products':adjustments}
