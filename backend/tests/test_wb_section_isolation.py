from types import SimpleNamespace
from app.connectors import WildberriesConnector

def test_wb_only_selected_section_is_requested():
    c = WildberriesConnector(SimpleNamespace(mode='api'), {'token':'test'})
    calls=[]
    def request(url, method='GET', payload=None, interval=0):
        calls.append(url)
        return {'orders':[{'id':123}]}
    c._request=request
    r=c.fetch(sections=['new_orders'])
    assert len(calls)==1 and '/orders/new' in calls[0]
    assert len(r.records)==1 and r.records[0]['record_type']=='new_order'

def test_wb_empty_section_is_independent():
    c=WildberriesConnector(SimpleNamespace(mode='api'), {'token':'test'})
    calls=[]
    c._request=lambda url, **kw: (calls.append(url) or [])
    r=c.fetch(sections=['sale'])
    assert len(calls)==1 and '/supplier/sales' in calls[0]
    assert r.records==[]
