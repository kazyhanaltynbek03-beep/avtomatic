from io import BytesIO
from types import SimpleNamespace
from urllib.error import HTTPError
from datetime import datetime, timezone

import pytest

from app import connectors
from app.connectors import connector, OzonConnector, KaspiConnector, WildberriesConnector, DemoAdapter, AccessRequired

def acc(channel, mode="api", ref=""):
    return SimpleNamespace(channel=channel, mode=mode, credential_ref=ref)

def test_kaspi_reports_missing_secret(monkeypatch):
    monkeypatch.delenv("KASPI_MAIN_TOKEN", raising=False)
    s = KaspiConnector(acc("Kaspi")).connection_status()
    assert s["configured"] is False
    assert s["missing"] == ["token"]

def test_ozon_uses_two_server_side_secrets(monkeypatch):
    s = OzonConnector(acc("Ozon", ref="SHOP"), {"client_id":"x"}).connection_status()
    assert s["configured"] is False
    assert s["missing"] == ["api_key"]


def test_ozon_uses_cursor_for_fbs_and_offset_for_fbo(monkeypatch):
    calls=[]
    def fake_request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        if "accrual/types" in url:
            return 200, {"types": []}
        if "accrual/by-day" in url:
            return 200, {"accruals": []}
        if "/v3/product/list" in url:
            return 200, {"result":{"items":[],"last_id":""}}
        if "/v3/product/info/list" in url:
            return 200, {"items":[]}
        if "/v4/product/info/attributes" in url:
            return 200, {"result":{"items":[],"last_id":""}}
        if "/v4/product/info/stocks" in url or "/v5/product/info/prices" in url:
            return 200, {"items":[],"cursor":""}
        calls.append((url,payload))
        if "/v4/posting/fbs/list" in url:
            if payload["cursor"] == "":
                return 200, {"postings":[{"posting_number":"fbs-1"}],"has_next":True,"cursor":"next"}
            return 200, {"postings":[{"posting_number":"fbs-2"}],"has_next":False,"cursor":""}
        if payload["offset"] == 0:
            return 200, {"result":{"postings":[{"posting_number":f"fbo-{i}"} for i in range(100)]}}
        return 200, {"result":{"postings":[{"posting_number":"fbo-last"}]}}
    monkeypatch.setattr(connectors, "_json_request", fake_request)
    result=OzonConnector(acc("Ozon"), {"client_id":"id","api_key":"key"}).fetch()
    fbs=[body for url,body in calls if "/v4/posting/fbs/list" in url]
    fbo=[body for url,body in calls if "/v3/posting/fbo/list" in url]
    assert len(result.records)==103
    assert fbs[0]["cursor"]=="" and fbs[1]["cursor"]=="next" and "offset" not in fbs[0]
    assert fbo[0]["offset"]==0 and fbo[1]["offset"]==100 and "cursor" not in fbo[0]


def test_connection_checks_are_lightweight_and_do_not_run_history_sync(monkeypatch):
    calls=[]
    def request(url, headers, **kwargs):
        calls.append((url,kwargs.get("payload")))
        if "ozon" in url: return 200,{"postings":[]}
        return 200,{"data":[]}
    monkeypatch.setattr(connectors,"_json_request",request)
    assert KaspiConnector(acc("Kaspi"),{"token":"x"}).test_connection()["records_checked"]==0
    assert OzonConnector(acc("Ozon"),{"client_id":"id","api_key":"key"}).test_connection()["records_checked"]==0
    assert len(calls)==2
    assert "page%5Bsize%5D=1" in calls[0][0]
    assert calls[1][1]["limit"]==1 and calls[1][1]["cursor"]==""

def test_kaspi_sync_starts_with_latest_week_then_walks_back(monkeypatch):
    calls = []
    def fake_request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        calls.append(url)
        if "/entries?" in url:
            return 200, {"data": [], "meta": {"pageCount": 0}}
        if "/orders?" in url:
            return 200, {"data": [{"id": "latest", "attributes": {
                "status": "COMPLETED", "creationDate": 1792627200000
            }}], "meta": {"pageCount": 1}}
        raise AssertionError(f"unexpected Kaspi route: {url}")
    monkeypatch.setattr(connectors, "_json_request", fake_request)
    c = KaspiConnector(acc("Kaspi"), {"token": "x"})
    first = c.fetch()
    first_state = connectors.json.loads(first.next_cursor)
    assert first_state["direction"] == "backward"
    first_start = first_state["start_ms"]
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    assert now_ms - first_start == pytest.approx(7 * 24 * 60 * 60 * 1000, abs=5000)

    second = c.fetch(first.next_cursor)
    second_state = connectors.json.loads(second.next_cursor)
    assert second_state["direction"] == "backward"
    assert second_state["start_ms"] < first_start
    assert first_start - second_state["start_ms"] == 7 * 24 * 60 * 60 * 1000


def test_kaspi_keeps_seller_and_return_delivery_fields_separate(monkeypatch):
    issued_ms=1792627200000
    def fake_request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        if "/entries?" in url:
            return 200, {"data": [], "meta": {"pageCount": 0}}
        if "/orders?" in url:
            return 200, {"data": [{"id":"returned-order","attributes":{
                "status":"RETURNED","creationDate":issued_ms,"completionDate":issued_ms+86400000,
                "deliveryCost":950,"deliveryCostForSeller":1250,"returnDeliveryCostForSeller":700,
                "returnDate":issued_ms+172800000,
            }}],"meta":{"pageCount":1}}
        raise AssertionError(f"unexpected Kaspi route: {url}")
    monkeypatch.setattr(connectors,"_json_request",fake_request)
    result=KaspiConnector(acc("Kaspi"),{"token":"x"}).fetch()
    order=next(x for x in result.records if x["record_type"]=="order")
    seller=next(x for x in result.records if x["record_type"]=="delivery_charge")
    returned=next(x for x in result.records if x["record_type"]=="return_delivery_charge")
    assert order["delivery_cost_for_buyer"]==950
    assert order["delivery_cost_for_seller"]==1250
    assert order["completion_date"]==issued_ms+86400000
    assert seller["amount"]==1250 and seller["order_status"]=="COMPLETED"
    assert returned["amount"]==700 and returned["returned_date"]==issued_ms+172800000


def test_kaspi_legacy_forward_cursor_restarts_at_latest_week(monkeypatch):
    def fake_request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        if "/entries?" in url:
            return 200, {"data": [], "meta": {"pageCount": 0}}
        if "/orders?" in url:
            return 200, {"data": [], "meta": {"pageCount": 0}}
        raise AssertionError(f"unexpected Kaspi route: {url}")
    monkeypatch.setattr(connectors, "_json_request", fake_request)
    legacy = connectors.json.dumps({
        "_qor_kaspi_cursor": 1, "start_ms": 1, "until_ms": 2, "page": 1, "offset": 50
    })
    result = KaspiConnector(acc("Kaspi"), {"token": "x"}).fetch(legacy)
    state = connectors.json.loads(result.next_cursor)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    assert state["direction"] == "backward"
    assert now_ms - state["start_ms"] == pytest.approx(7 * 24 * 60 * 60 * 1000, abs=5000)


def test_wildberries_connection_test_checks_finance_permissions(monkeypatch):
    calls=[]
    def fake_request(url, token, payload):
        calls.append((url, token, payload))
        return 204, {}
    monkeypatch.setattr("app.wb_weekly._request", fake_request)
    result=WildberriesConnector(acc("Wildberries"), {"token":"private-token"}).test_connection()
    assert "Finance API WB" in result["message"]
    assert result["records_checked"] == 0
    assert len(calls) == 1
    assert calls[0][1] == "private-token"
    assert calls[0][2]["period"] == "daily" and calls[0][2]["limit"] == 1

def test_demo_is_explicitly_non_live():
    c = connector(acc("Kaspi", mode="demo"))
    assert isinstance(c, DemoAdapter)
    assert c.connection_status()["live"] is False
    assert c.fetch().source == "demo"


def test_transient_marketplace_error_retries_without_exposing_response_body(monkeypatch):
    calls = []

    class Response:
        status = 200
        def read(self): return b"{}"
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def request(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError("https://marketplace.example", 429, "Too many", {}, BytesIO(b"token=must-not-leak"))
        return Response()

    monkeypatch.setattr(connectors, "urlopen", request)
    monkeypatch.setattr(connectors.time, "sleep", lambda *_: None)
    assert connectors._json_request("https://marketplace.example", {}, retries=1) == (200, {})
    assert len(calls) == 2


def test_marketplace_error_never_reflects_provider_response_body(monkeypatch):
    monkeypatch.setattr(connectors, "urlopen", lambda *a, **k: (_ for _ in ()).throw(
        HTTPError("https://marketplace.example", 400, "Bad", {}, BytesIO(b"secret-token=leak"))
    ))
    try:
        connectors._json_request("https://marketplace.example", {}, retries=0)
        assert False, "expected safe connector error"
    except AccessRequired as exc:
        assert "secret-token" not in str(exc)

def test_ozon_accrual_null_posting_does_not_crash_sync(monkeypatch):
    def fake_request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        if "accrual" in url:
            # Real Ozon responses may contain posting: null.
            if payload.get("last_id") == "":
                return 200, {"accruals": [{"id": None, "posting": None, "amount": 10}], "last_id": "next"}
            return 200, {"accruals": [], "last_id": ""}
        return 200, {"postings": [], "has_next": False, "cursor": ""}
    monkeypatch.setattr(connectors, "_json_request", fake_request)
    result = OzonConnector(acc("Ozon"), {"client_id":"id", "api_key":"key"}).fetch()
    accruals = [r for r in result.records if r.get("record_type") == "finance_accrual"]
    assert accruals
    assert accruals[0]["external_id"].startswith("accrual:")
