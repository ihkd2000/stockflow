
def test_each_page_returns_navigation_and_forms(client):
    paths = ['dashboard','inventory','products','warehouses','purchasing',
             'reservations','counts','risks','activity']
    for page in paths:
        response = client.get('/' + page)
        assert response.status_code == 200
        assert 'id="page-' + page + '"' in response.text
        assert 'data-page-link="' + page + '"' in response.text

def test_unknown_page_is_404(client):
    assert client.get('/not-a-stockflow-page').status_code == 404

def test_legacy_entry_point_works(client):
    assert client.get('/').status_code == 200
    assert 'StockFlow' in client.get('/').text

def test_ui_workflow_elements_still_exist(client):
    html = client.get('/').text
    for form in ('product-form','warehouse-form','operation','supplier-form',
                 'po-form','reservation-form','count-form','risk-form'):
        assert 'id="' + form + '"' in html
    assert html.count('id="toast"') == 1
