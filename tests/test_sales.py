def make(client):
    p=client.post('/api/products',json={'sku':'SALES-A','name':'A'}).json()['id']
    q=client.post('/api/products',json={'sku':'SALES-B','name':'B'}).json()['id']
    w=client.post('/api/warehouses',json={'code':'SALES','name':'Sales'}).json()['id']
    for pid in (p,q):
        assert client.post('/api/operations',json={'kind':'RECEIVE','product_id':pid,'warehouse_id':w,'quantity':10}).status_code==200
    return p,q,w

def order(client,p,q,w,number='SO-1'):
    response=client.post('/api/sales-orders',json={'number':number,'warehouse_id':w,'lines':[{'product_id':p,'quantity':7},{'product_id':q,'quantity':5}]})
    assert response.status_code==201,response.text
    return response.json()

def test_multiline_partial_fulfillment_retry_and_completion(client):
    p,q,w=make(client);o=order(client,p,q,w);oid=o['id'];line=o['lines'][0]['id']
    assert client.post(f'/api/sales-orders/{oid}/allocate').status_code==409
    assert client.post(f'/api/sales-orders/{oid}/confirm').json()['status']=='CONFIRMED'
    assert client.post(f'/api/sales-orders/{oid}/allocate').status_code==200
    assert client.post(f'/api/sales-orders/{oid}/allocate').status_code==200
    res=client.get('/api/reservations').json()
    rid=next(r['id'] for r in res if r['product_id']==p)
    assert client.post(f'/api/reservations/{rid}/fulfill').status_code==409
    assert client.post('/api/operations',json={'kind':'ISSUE','product_id':p,'warehouse_id':w,'quantity':4}).status_code==409
    url=f'/api/sales-orders/{oid}/lines/{line}/fulfill'
    payload={'quantity':3,'idempotency_key':'ful-1'}
    first=client.post(url,json=payload)
    assert first.status_code==200,first.text
    assert first.json()['status']=='PARTIAL'
    assert client.post(url,json=payload).json()==first.json()
    assert client.post(url,json={'quantity':2,'idempotency_key':'ful-1'}).status_code==409
    assert client.post(url,json={'quantity':5,'idempotency_key':'ful-2'}).status_code==409
    assert client.post(url,json={'quantity':4,'idempotency_key':'ful-3'}).status_code==200
    other=o['lines'][1]['id']
    done=client.post(f'/api/sales-orders/{oid}/lines/{other}/fulfill',json={'quantity':5,'idempotency_key':'ful-4'})
    assert done.json()['status']=='FULFILLED'
    assert client.post(f'/api/sales-orders/{oid}/cancel').status_code==409
    assert client.get('/api/availability').json()[0]['available']==3
    assert len([r for r in client.get('/api/movements').json() if r['action']=='ISSUE'])==3

def test_cancel_partial_releases_only_remaining(client):
    p,q,w=make(client);o=order(client,p,q,w,'SO-2');oid=o['id']
    client.post(f'/api/sales-orders/{oid}/confirm');client.post(f'/api/sales-orders/{oid}/allocate')
    line=o['lines'][0]['id']
    assert client.post(f'/api/sales-orders/{oid}/lines/{line}/fulfill',json={'quantity':2,'idempotency_key':'part'}).status_code==200
    assert client.post(f'/api/sales-orders/{oid}/cancel').json()['status']=='CANCELLED'
    availability=client.get('/api/availability').json()
    assert all(a['reserved']==0 for a in availability)
    assert next(a['on_hand'] for a in availability if a['sku']=='SALES-A')==8
    assert client.post(f'/api/sales-orders/{oid}/allocate').status_code==409

def test_allocation_atomic_and_draft_edit(client):
    p,q,w=make(client);o=order(client,p,q,w,'SO-3');oid=o['id']
    edited=client.put(f'/api/sales-orders/{oid}',json={'lines':[{'product_id':p,'quantity':2},{'product_id':q,'quantity':12}]})
    assert edited.status_code==200
    client.post(f'/api/sales-orders/{oid}/confirm')
    assert client.post(f'/api/sales-orders/{oid}/allocate').status_code==409
    assert not [x for x in client.get('/api/reservations').json() if x['status']=='ACTIVE']
    assert client.put(f'/api/sales-orders/{oid}',json={'lines':[{'product_id':p,'quantity':1}]}).status_code==409

def test_duplicate_order_and_inactive_product(client):
    p,q,w=make(client);order(client,p,q,w,'SO-4')
    assert client.post('/api/sales-orders',json={'number':'SO-4','warehouse_id':w,'lines':[{'product_id':p,'quantity':1}]}).status_code==409
    assert client.post('/api/sales-orders',json={'number':'BAD','warehouse_id':w,'lines':[{'product_id':p,'quantity':1},{'product_id':p,'quantity':2}]}).status_code==400
    assert client.get('/sales').status_code==200
