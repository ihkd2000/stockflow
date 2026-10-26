def op(client, product, wh, kind, quantity, **kwargs):
    return client.post('/api/operations', json={'kind':kind,'product_id':product,
                       'warehouse_id':wh,'quantity':quantity,**kwargs})


def test_create_products_and_warehouses(client, setup_data):
    assert client.get('/api/products').json()[0]['sku'] == 'WIDGET-A'
    assert len(client.get('/api/warehouses').json()) == 2
    assert client.post('/api/products', json={'sku':'widget-a','name':'Duplicate'}).status_code == 409


def test_receive_issue_and_reorder(client, setup_data):
    p,a,_ = setup_data
    assert len(client.get('/api/reorder').json()) == 2
    assert op(client,p,a,'RECEIVE',10).status_code == 200
    assert op(client,p,a,'ISSUE',8).status_code == 200
    assert next(r for r in client.get('/api/stock').json() if r['warehouse_id']==a)['quantity']==2
    assert len(client.get('/api/movements').json())==2


def test_no_negative_stock(client, setup_data):
    p,a,_=setup_data
    assert op(client,p,a,'ISSUE',1).status_code==409
    assert client.get('/api/movements').json()==[]


def test_transfer_is_atomic(client, setup_data):
    p,a,b=setup_data
    op(client,p,a,'RECEIVE',5)
    assert op(client,p,a,'TRANSFER',6,target_warehouse_id=b).status_code==409
    assert len(client.get('/api/movements').json())==1
    assert op(client,p,a,'TRANSFER',3,target_warehouse_id=b).status_code==200
    quantities={r['warehouse_id']:r['quantity'] for r in client.get('/api/stock').json()}
    assert quantities == {a:2,b:3}
    transfers=[r for r in client.get('/api/movements').json() if r['action'].startswith('TRANSFER')]
    assert len(transfers)==2 and transfers[0]['transfer_group']==transfers[1]['transfer_group']


def test_idempotent_replay(client, setup_data):
    p,a,_=setup_data
    payload={'kind':'RECEIVE','product_id':p,'warehouse_id':a,'quantity':4}
    headers={'Idempotency-Key':'receive-001'}
    first=client.post('/api/operations',json=payload,headers=headers)
    second=client.post('/api/operations',json=payload,headers=headers)
    assert first.json()==second.json()
    assert len(client.get('/api/movements').json())==1
    payload['quantity']=5
    assert client.post('/api/operations',json=payload,headers=headers).status_code==409


def test_adjustment_and_validation(client, setup_data):
    p,a,b=setup_data
    assert op(client,p,a,'ADJUST',-1).status_code==409
    op(client,p,a,'RECEIVE',5)
    assert op(client,p,a,'ADJUST',-2).status_code==200
    assert op(client,p,a,'TRANSFER',1,target_warehouse_id=a).status_code==400
    assert op(client,p,a,'RECEIVE',0).status_code==400
    assert op(client,p,a,'TRANSFER',1,target_warehouse_id=999).status_code==404
    assert client.get('/api/stock').json()[0]['quantity']==3


def test_no_personal_data_fields(client):
    html=client.get('/')
    assert html.status_code==200
    schema=client.get('/openapi.json').json()
    for name in ('ProductIn','WarehouseIn','OperationIn'):
        fields=schema['components']['schemas'][name]['properties']
        assert not set(fields).intersection({'email','phone','address','first_name','last_name'})