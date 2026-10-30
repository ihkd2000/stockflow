from stockflow.db import connect

def setup(client):
    product=client.post('/api/products',json={'sku':'TEST-PART','name':'Part'}).json()['id']
    warehouse=client.post('/api/warehouses',json={'code':'MAIN','name':'Main'}).json()['id']
    supplier=client.post('/api/suppliers',json={'code':'ORG','organization_name':'Sample Supply Co'}).json()['id']
    return product,warehouse,supplier

def test_purchase_order_partial_receipts_and_retry(client):
    p,w,s=setup(client)
    o=client.post('/api/purchase-orders',json={'number':'PO-001','supplier_id':s,'warehouse_id':w,'lines':[{'product_id':p,'quantity':10}]})
    assert o.status_code==201
    oid=o.json()['id']
    line=client.get(f'/api/purchase-orders/{oid}/lines').json()[0]['id']
    assert client.post(f'/api/purchase-orders/{oid}/lines/{line}/receive',json={'quantity':3,'idempotency_key':'r1'}).status_code==409
    assert client.post(f'/api/purchase-orders/{oid}/submit').json()['status']=='OPEN'
    path=f'/api/purchase-orders/{oid}/lines/{line}/receive'
    r=client.post(path,json={'quantity':3,'idempotency_key':'r1'})
    assert r.json()['status']=='PARTIAL'
    assert client.post(path,json={'quantity':3,'idempotency_key':'r1'}).json()==r.json()
    assert client.post(path,json={'quantity':8,'idempotency_key':'r2'}).status_code==409
    assert client.post(path,json={'quantity':7,'idempotency_key':'r3'}).json()['status']=='RECEIVED'
    assert client.get('/api/stock').json()[0]['quantity']==10
    assert len(client.get('/api/movements').json())==2

def test_reserved_stock_cannot_be_issued_transferred_or_adjusted(client):
    p,w,s=setup(client)
    other=client.post('/api/warehouses',json={'code':'OTHER','name':'Other'}).json()['id']
    assert client.post('/api/operations',json={'kind':'RECEIVE','product_id':p,'warehouse_id':w,'quantity':10}).status_code==200
    reserve=client.post('/api/reservations',json={'reference':'ALLOC-1','product_id':p,'warehouse_id':w,'quantity':8})
    assert reserve.status_code==201
    rid=reserve.json()['id']
    def operation(kind,quantity,**extra):
        return client.post('/api/operations',json={'kind':kind,'product_id':p,'warehouse_id':w,'quantity':quantity,**extra})
    assert operation('ISSUE',3).status_code==409
    assert operation('TRANSFER',3,target_warehouse_id=other).status_code==409
    assert operation('ADJUST',-3).status_code==409
    assert client.get('/api/availability').json()[0]['available']==2
    assert operation('ISSUE',2).status_code==200
    assert client.post(f'/api/reservations/{rid}/fulfill').json()['status']=='FULFILLED'
    assert client.post(f'/api/reservations/{rid}/fulfill').status_code==409
    assert client.get('/api/stock').json()[0]['quantity']==0

def test_cancel_and_duplicates(client):
    p,w,s=setup(client)
    payload={'number':'PO-2','supplier_id':s,'warehouse_id':w,'lines':[{'product_id':p,'quantity':2}]}
    assert client.post('/api/purchase-orders',json=payload).status_code==201
    assert client.post('/api/purchase-orders',json=payload).status_code==409
    assert client.post('/api/purchase-orders/1/cancel').json()['status']=='CANCELLED'
    assert client.post('/api/purchase-orders/1/submit').status_code==409
    assert client.post('/api/reservations',json={'reference':'NOSTOCK','product_id':p,'warehouse_id':w,'quantity':1}).status_code==409
