"""Explainable, read-only inventory coverage and transfer recommendations."""
import math
from .db import connect
from .service import DomainError


def configure(product_id: int, warehouse_id: int, daily_demand: float, lead_days: int, safety_days: int):
    if daily_demand < 0 or lead_days < 0 or safety_days < 0 or daily_demand > 1_000_000:
        raise DomainError('Demand and planning days must be nonnegative and within limits')
    with connect(write=True) as db:
        if not db.execute('SELECT 1 FROM products WHERE id=? AND active=1', (product_id,)).fetchone():
            raise DomainError('Unknown or inactive product', 404)
        if not db.execute('SELECT 1 FROM warehouses WHERE id=?', (warehouse_id,)).fetchone():
            raise DomainError('Unknown warehouse', 404)
        db.execute('''INSERT INTO risk_policies(product_id,warehouse_id,daily_demand,lead_days,safety_days)
          VALUES(?,?,?,?,?) ON CONFLICT(product_id,warehouse_id) DO UPDATE SET
          daily_demand=excluded.daily_demand,lead_days=excluded.lead_days,safety_days=excluded.safety_days''',
          (product_id,warehouse_id,daily_demand,lead_days,safety_days))
    return {'product_id': product_id, 'warehouse_id': warehouse_id, 'daily_demand':daily_demand,
            'lead_days':lead_days,'safety_days':safety_days}


def assess():
    with connect() as db:
        records = db.execute('''SELECT p.id product_id,p.sku,p.name product,w.id warehouse_id,w.code warehouse,
          COALESCE(b.quantity,0) on_hand,
          COALESCE((SELECT SUM(r.quantity) FROM reservations r WHERE r.product_id=p.id AND r.warehouse_id=w.id AND r.status='ACTIVE'),0) reserved,
          COALESCE(c.daily_demand,0) daily_demand,c.lead_days,c.safety_days,p.reorder_point
          FROM products p CROSS JOIN warehouses w
          LEFT JOIN balances b ON b.product_id=p.id AND b.warehouse_id=w.id
          LEFT JOIN risk_policies c ON c.product_id=p.id AND c.warehouse_id=w.id
          WHERE p.active=1 ORDER BY p.sku,w.code''').fetchall()
        items = [dict(r) for r in records]
        for item in items:
            available = item['on_hand']-item['reserved']
            item['available'] = available
            item['configured'] = item['lead_days'] is not None
            item['recommendations'] = []
            if not item['configured']:
                item.update(risk='UNCONFIGURED',coverage_days=None, target_quantity=None,
                            shortfall=None, explanation='Set demand, supplier lead time and safety buffer to calculate risk.')
                continue
            demand = item['daily_demand']
            lead = item['lead_days']
            safety = item['safety_days']
            target = math.ceil(demand*(lead+safety))
            shortfall = max(0,target-available)
            coverage = (round(available/demand, 2) if demand > 0 else None)
            risk = ('HIGH' if demand > 0 and available < demand*lead else
                    'MODERATE' if demand > 0 and available < demand*(lead+safety) else 'LOW')
            item.update(risk=risk, coverage_days=coverage,target_quantity=target,shortfall=shortfall,
                        explanation=(f'{available} free units; {demand:g}/day demand; {lead} day lead time; '
                                     f'{safety} day buffer. Target {target} units. '
                                     'Incoming orders have no confirmed delivery dates and are excluded.'))
        for item in items:
            if not item['configured'] or not item['shortfall']:
                continue
            for donor in items:
                if donor['product_id'] != item['product_id'] or donor['warehouse_id'] == item['warehouse_id']:
                    continue
                # Never transfer reserved stock or a configured donor's safety target.
                donor_floor = donor['target_quantity'] if donor['configured'] else donor['reorder_point']
                surplus = max(0,donor['available']-donor_floor)
                if surplus:
                    item['recommendations'].append({'kind':'TRANSFER_REVIEW','from_warehouse_id':donor['warehouse_id'],
                        'from_warehouse':donor['warehouse'],'suggested_quantity':min(item['shortfall'],surplus),
                        'note':'Read-only estimate. Recheck live availability, open counts and transfer rules before execution.'})
            if item['shortfall']:
                item['recommendations'].append({'kind':'REPLENISHMENT_REVIEW','suggested_quantity':item['shortfall'],
                    'note':'Review purchasing and delivery dates. No purchase order has been created.'})
        return items
