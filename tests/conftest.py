import pytest
from fastapi.testclient import TestClient
from stockflow.api import app
from stockflow.db import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('STOCKFLOW_DB', str(tmp_path / 'test.db'))
    init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def setup_data(client):
    p = client.post('/api/products', json={'sku':'WIDGET-A','name':'Widget A','reorder_point':3}).json()
    w1 = client.post('/api/warehouses', json={'code':'EAST','name':'East Warehouse'}).json()
    w2 = client.post('/api/warehouses', json={'code':'WEST','name':'West Warehouse'}).json()
    return p['id'], w1['id'], w2['id']