
def new_count(client, warehouse, ref='Annual audit'):
    return client.post('/api/counts',json={'warehouse_id':warehouse,'reference':ref})


def count_lines(client, count_id):
    return client.get(f'/api/counts/{count_id}/lines').json()


def record(client,count_id,pid,quantity):
    return client.put(f'/api/counts/{count_id}/lines/{pid}',json={'quantity':quantity})


def test_count_adjustment_audited_and_replay_safe(client,setup_data):
    pid,wid,_=setup_data
    client.post('/api/operations',json={'kind':'RECEIVE','product_id':pid,'warehouse_id':wid,'quantity':10})
    resp=new_count(client,wid)
    assert resp.status_code==201
    cid=resp.json()['id']
    assert count_lines(client,cid)[0]['expected']==10
    assert record(client,cid,pid,7).status_code==200
    result=client.post(f'/api/counts/{cid}/apply')
    assert result.status_code==200
    assert result.json()['adjusted_products']==1
    assert client.post(f'/api/counts/{cid}/apply').json()['replayed'] is True
    stock=client.get('/api/stock').json()
    assert next(x for x in stock if x['product_id']==pid and x['warehouse_id']==wid)['quantity']==7
    movements=client.get('/api/movements').json()
    assert len([m for m in movements if m['action']=='ADJUST' and m['reference'].startswith('COUNT-')])==1


def test_requires_all_counted_and_rejects_duplicate_open(client,setup_data):
    pid,wid,_=setup_data
    cid=new_count(client,wid).json()['id']
    assert new_count(client,wid).status_code==409
    assert client.post(f'/api/counts/{cid}/apply').status_code==409
    assert record(client,cid,pid,0).status_code==200
    assert client.post(f'/api/counts/{cid}/cancel').status_code==200
    assert new_count(client,wid).status_code==201


def test_stale_count_cannot_overwrite_new_movements(client,setup_data):
    pid,wid,_=setup_data
    cid=new_count(client,wid).json()['id']
    record(client,cid,pid,5)
    client.post('/api/operations',json={'kind':'RECEIVE','product_id':pid,'warehouse_id':wid,'quantity':1})
    assert client.post(f'/api/counts/{cid}/apply').status_code==409
    assert client.get('/api/counts').json()[0]['status']=='OPEN'


def test_count_respects_reservations(client,setup_data):
    pid,wid,_=setup_data
    client.post('/api/operations',json={'kind':'RECEIVE','product_id':pid,'warehouse_id':wid,'quantity':10})
    reservation=client.post('/api/reservations',json={'reference':'ORDER-1','product_id':pid,'warehouse_id':wid,'quantity':8})
    assert reservation.status_code==201
    cid=new_count(client,wid).json()['id']
    record(client,cid,pid,7)
    assert client.post(f'/api/counts/{cid}/apply').status_code==409
    assert client.get('/api/stock').json()[0]['quantity']==10


def test_cancel_is_safe_and_prevents_changes(client,setup_data):
    pid,wid,_=setup_data
    cid=new_count(client,wid).json()['id']
    assert client.post(f'/api/counts/{cid}/cancel').status_code==200
    assert record(client,cid,pid,2).status_code==409
    assert client.post(f'/api/counts/{cid}/apply').status_code==409
