def test_unconfigured_and_risk_policy(client, setup_data):
    pid, east, west = setup_data
    rows = client.get('/api/inventory-risks').json()
    assert len(rows) == 2 and all(r['risk'] == 'UNCONFIGURED' for r in rows)
    assert client.put('/api/risk-policies', json={'product_id':pid,'warehouse_id':east,'daily_demand':5,'lead_days':7,'safety_days':2}).status_code == 200
    row = next(r for r in client.get('/api/inventory-risks').json() if r['warehouse_id']==east)
    assert row['risk']=='HIGH' and row['shortfall']==45 and row['target_quantity']==45
    assert any(a['kind']=='REPLENISHMENT_REVIEW' for a in row['recommendations'])


def test_transfer_excludes_reserved_and_donor_buffer(client, setup_data):
    pid, east, west = setup_data
    for wid, demand in [(east, 10),(west, 1)]:
        assert client.put('/api/risk-policies',json={'product_id':pid,'warehouse_id':wid,'daily_demand':demand,'lead_days':5,'safety_days':1}).status_code==200
    assert client.post('/api/operations',json={'kind':'RECEIVE','product_id':pid,'warehouse_id':west,'quantity':45}).status_code==200
    assert client.post('/api/reservations',json={'reference':'hold-1','product_id':pid,'warehouse_id':west,'quantity':10}).status_code==201
    data=client.get('/api/inventory-risks').json()
    receiving=next(x for x in data if x['warehouse_id']==east)
    transfer=next(x for x in receiving['recommendations'] if x['kind']=='TRANSFER_REVIEW')
    assert transfer['suggested_quantity']==29  # 45 - reserved 10 - target 6
    assert client.get('/api/availability').json()[0]['available'] == 0
    assert len(client.get('/api/movements').json()) == 1  # read-only risk calculation


def test_no_unsafe_transfer_and_zero_demand(client, setup_data):
    pid, east, west=setup_data
    for wid, demand in [(east,4),(west,0)]:
        client.put('/api/risk-policies',json={'product_id':pid,'warehouse_id':wid,'daily_demand':demand,'lead_days':3,'safety_days':2})
    client.post('/api/operations',json={'kind':'RECEIVE','product_id':pid,'warehouse_id':west,'quantity':5})
    client.post('/api/reservations',json={'reference':'reserved-all','product_id':pid,'warehouse_id':west,'quantity':5})
    data=client.get('/api/inventory-risks').json()
    assert next(x for x in data if x['warehouse_id']==east)['recommendations'][0]['kind']=='REPLENISHMENT_REVIEW'
    assert next(x for x in data if x['warehouse_id']==west)['risk']=='LOW'
    assert client.put('/api/risk-policies',json={'product_id':pid,'warehouse_id':east,'daily_demand':-1,'lead_days':1,'safety_days':0}).status_code==422
