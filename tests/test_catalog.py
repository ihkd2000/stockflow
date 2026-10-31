import csv
import io


def test_catalog_search_filter_sort_and_pagination(client):
    for sku, category in [('AAA','Parts'),('BBB','Parts'),('CCC','Tools')]:
        assert client.post('/api/products',json={'sku':sku,'name':f'{sku} unit','category':category}).status_code == 201
    r = client.get('/api/products/catalog',params={'category':'Parts','page_size':1,'page':2,'sort':'sku','descending':'true'})
    assert r.status_code == 200
    data=r.json()
    assert data['total']==2 and data['pages']==2 and data['items'][0]['sku']=='AAA'
    assert client.get('/api/products/catalog',params={'search':'AAA'}).json()['total']==1
    assert client.get('/api/products/catalog',params={'page_size':101}).status_code==400
    assert len(client.get('/api/products').json())==3


def test_edit_duplicate_and_details(client,setup_data):
    pid,wid,_=setup_data
    p=client.post('/api/products',json={'sku':'DIFFERENT','name':'Other'}).json()
    assert client.put(f'/api/products/{pid}',json={'sku':'different','name':'Name','category':'Components','reorder_point':8}).status_code==409
    updated=client.put(f'/api/products/{pid}',json={'sku':'widget-b','name':'Renamed','category':'Parts','reorder_point':6})
    assert updated.status_code==200 and updated.json()['sku']=='WIDGET-B'
    assert client.post('/api/operations',json={'kind':'RECEIVE','product_id':pid,'warehouse_id':wid,'quantity':12}).status_code==200
    result=client.get(f'/api/products/{pid}').json()
    assert result['stock'][0]['on_hand']==12 and result['movements'][0]['delta']==12
    assert client.get('/api/products/99999').status_code==404


def test_deactivation_preserves_history_and_blocks_new_operations(client,setup_data):
    pid,wid,_=setup_data
    assert client.post('/api/operations',json={'kind':'RECEIVE','product_id':pid,'warehouse_id':wid,'quantity':10}).status_code==200
    assert client.patch(f'/api/products/{pid}/status',json={'active':False}).status_code==200
    assert client.get('/api/products/catalog',params={'status':'inactive'}).json()['total']==1
    assert client.post('/api/operations',json={'kind':'ISSUE','product_id':pid,'warehouse_id':wid,'quantity':1}).status_code==409
    assert client.post('/api/reservations',json={'reference':'R1','product_id':pid,'warehouse_id':wid,'quantity':1}).status_code==409
    assert client.get(f'/api/products/{pid}').json()['stock'][0]['on_hand']==10
    assert client.patch(f'/api/products/{pid}/status',json={'active':True}).status_code==200


def test_deactivation_rejects_outstanding_commitments(client,setup_data):
    pid,wid,_=setup_data
    client.post('/api/operations',json={'kind':'RECEIVE','product_id':pid,'warehouse_id':wid,'quantity':5})
    reservation=client.post('/api/reservations',json={'reference':'HOLD','product_id':pid,'warehouse_id':wid,'quantity':2}).json()
    assert client.patch(f'/api/products/{pid}/status',json={'active':False}).status_code==409
    assert client.post(f"/api/reservations/{reservation['id']}/release").status_code==200
    assert client.patch(f'/api/products/{pid}/status',json={'active':False}).status_code==200


def test_csv_export_quotes_fields_and_respects_filter(client):
    client.post('/api/products',json={'sku':'EXPORT','name':'Widget, "Special"','category':'Sales'})
    client.post('/api/products',json={'sku':'EXCLUDE','name':'Other','category':'Parts'})
    r=client.get('/api/products/export',params={'category':'Sales'})
    assert r.status_code==200 and r.headers['content-type'].startswith('text/csv')
    records=list(csv.DictReader(io.StringIO(r.text)))
    assert len(records)==1 and records[0]['Name']=='Widget, "Special"'
