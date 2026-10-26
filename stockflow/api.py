from pathlib import Path
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from . import service
from .db import init_db, init_commerce_db

@asynccontextmanager
async def lifespan(_app):
    init_db()
    init_commerce_db()
    yield


app = FastAPI(title='StockFlow', version='0.1.0', lifespan=lifespan)


@app.exception_handler(service.DomainError)
def domain_error(_, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=exc.status, content={'detail': str(exc)})


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(default='General', max_length=80)
    reorder_point: int = Field(default=0, ge=0)


class WarehouseIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)


class OperationIn(BaseModel):
    kind: Literal['RECEIVE', 'ISSUE', 'TRANSFER', 'ADJUST']
    product_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    quantity: int
    target_warehouse_id: int | None = None
    reference: str = Field(default='', max_length=120)


@app.get('/', response_class=HTMLResponse, include_in_schema=False)
def index():
    return (Path(__file__).parent / 'static' / 'index.html').read_text(encoding='utf-8')


@app.get('/api/products')
def products():
    return service.rows('SELECT * FROM products ORDER BY sku')


@app.post('/api/products', status_code=201)
def create_product(payload: ProductIn):
    return service.add_product(**payload.model_dump())


@app.get('/api/warehouses')
def warehouses():
    return service.rows('SELECT * FROM warehouses ORDER BY code')


@app.post('/api/warehouses', status_code=201)
def create_warehouse(payload: WarehouseIn):
    return service.add_warehouse(**payload.model_dump())


@app.get('/api/stock')
def stock():
    return service.rows('''SELECT p.id product_id,p.sku,p.name product,w.id warehouse_id,w.code warehouse,
        COALESCE(b.quantity,0) quantity,p.reorder_point
        FROM products p CROSS JOIN warehouses w LEFT JOIN balances b
        ON b.product_id=p.id AND b.warehouse_id=w.id ORDER BY p.sku,w.code''')


@app.get('/api/reorder')
def reorder():
    return [r for r in stock() if r['quantity'] <= r['reorder_point']]


@app.get('/api/movements')
def movements(limit: int = 100):
    if not 1 <= limit <= 500:
        raise HTTPException(400, 'Limit must be between 1 and 500')
    return service.rows('''SELECT m.id,m.created_at,m.action,p.sku,w.code warehouse,m.delta,m.reference,m.transfer_group
        FROM movements m JOIN products p ON p.id=m.product_id JOIN warehouses w ON w.id=m.warehouse_id
        ORDER BY m.id DESC LIMIT ?''', (limit,))


@app.post('/api/operations')
def operation(payload: OperationIn, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key')):
    return service.operate(**payload.model_dump(), key=idempotency_key)


from . import commerce

class SupplierIn(BaseModel):
    code: str = Field(min_length=1)
    organization_name: str = Field(min_length=1)

class OrderLineIn(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)

class PurchaseOrderIn(BaseModel):
    number: str = Field(min_length=1)
    supplier_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    lines: list[OrderLineIn] = Field(min_length=1)

class ReceiptIn(BaseModel):
    quantity: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1)

class ReservationIn(BaseModel):
    reference: str = Field(min_length=1)
    product_id: int = Field(gt=0)
    warehouse_id: int = Field(gt=0)
    quantity: int = Field(gt=0)

@app.get('/api/suppliers')
def suppliers():
    return commerce.list_rows('SELECT * FROM suppliers ORDER BY code')

@app.post('/api/suppliers',status_code=201)
def create_supplier(data:SupplierIn):
    return commerce.supplier(**data.model_dump())

@app.get('/api/purchase-orders')
def purchase_orders():
    return commerce.list_rows("SELECT o.*,s.organization_name supplier,w.code warehouse FROM purchase_orders o JOIN suppliers s ON s.id=o.supplier_id JOIN warehouses w ON w.id=o.warehouse_id ORDER BY o.id DESC")

@app.get('/api/purchase-orders/{order_id}/lines')
def purchase_order_lines(order_id:int):
    return commerce.list_rows('SELECT l.*,p.sku FROM purchase_order_lines l JOIN products p ON p.id=l.product_id WHERE l.order_id=? ORDER BY l.id',(order_id,))

@app.post('/api/purchase-orders',status_code=201)
def new_order(data:PurchaseOrderIn):
    return commerce.create_order(**data.model_dump())

@app.post('/api/purchase-orders/{order_id}/{action}')
def transition_order(order_id:int, action:Literal['submit','cancel']):
    return commerce.change_order_status(order_id,action)

@app.post('/api/purchase-orders/{order_id}/lines/{line_id}/receive')
def receive_order_line(order_id:int,line_id:int,data:ReceiptIn):
    return commerce.receive_line(order_id,line_id,data.quantity,data.idempotency_key)

@app.get('/api/availability')
def availability():
    return commerce.list_rows("SELECT p.sku,w.code warehouse,coalesce(b.quantity,0) on_hand,coalesce((SELECT sum(r.quantity) FROM reservations r WHERE r.product_id=p.id AND r.warehouse_id=w.id AND r.status='ACTIVE'),0) reserved,coalesce(b.quantity,0)-coalesce((SELECT sum(r.quantity) FROM reservations r WHERE r.product_id=p.id AND r.warehouse_id=w.id AND r.status='ACTIVE'),0) available FROM products p CROSS JOIN warehouses w LEFT JOIN balances b ON p.id=b.product_id AND w.id=b.warehouse_id ORDER BY p.sku,w.code")

@app.get('/api/reservations')
def reservations():
    return commerce.list_rows('SELECT * FROM reservations ORDER BY id DESC')

@app.post('/api/reservations',status_code=201)
def new_reservation(data:ReservationIn):
    return commerce.reserve(**data.model_dump())

@app.post('/api/reservations/{reservation_id}/{action}')
def reservation_action(reservation_id:int,action:Literal['release','fulfill']):
    return commerce.finalize_reservation(reservation_id,action)