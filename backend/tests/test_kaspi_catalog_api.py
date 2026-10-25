from types import SimpleNamespace

import pytest

from app import connectors
from app.connectors import AccessRequired, KaspiConnector


def account():
    return SimpleNamespace(channel="Kaspi", mode="api", credential_ref="")


def test_kaspi_catalog_uses_documented_routes_and_server_token(monkeypatch):
    calls = []

    def request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        calls.append((url, headers, method, payload))
        return 200, {"data": []}

    monkeypatch.setattr(connectors, "_json_request", request)
    client = KaspiConnector(account(), {"token": "server-only-token"})
    client.list_categories()
    client.list_category_attributes("Phones and Gadgets")
    client.list_attribute_values("Phones and Gadgets", "brand")

    assert calls[0][0].endswith("/products/classification/categories")
    assert "c=Phones+and+Gadgets" in calls[1][0]
    assert "c=Phones+and+Gadgets" in calls[2][0] and "a=brand" in calls[2][0]
    assert all(call[1]["X-Auth-Token"] == "server-only-token" for call in calls)
    assert all("server-only-token" not in str(call[0]) for call in calls)


def test_kaspi_product_import_is_bounded_and_checks_required_fields(monkeypatch):
    calls = []

    def request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        calls.append((url, headers, method, payload))
        return 200, {"code": "import-123"}

    monkeypatch.setattr(connectors, "_json_request", request)
    client = KaspiConnector(account(), {"token": "server-only-token"})
    product = {"sku": "SKU-1", "title": "Sample", "brand": "Brand", "category": "Category"}
    assert client.import_products([product]) == {"code": "import-123"}
    assert calls[0][0].endswith("/shop/api/products/import")
    assert calls[0][1]["Content-Type"] == "text/plain"
    assert calls[0][2] == "POST" and calls[0][3] == [product]

    with pytest.raises(AccessRequired, match="заполните brand"):
        client.import_products([{**product, "brand": ""}])
    with pytest.raises(AccessRequired, match="от 1 до 100"):
        client.import_products([product] * 101)
    with pytest.raises(AccessRequired, match="до 20 символов"):
        client.import_products([{**product, "sku": "S" * 21}])


def test_kaspi_product_import_status_and_result_are_read_only(monkeypatch):
    calls = []

    def request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        calls.append((url, method))
        return 200, {"status": "FINISHED"}

    monkeypatch.setattr(connectors, "_json_request", request)
    client = KaspiConnector(account(), {"token": "server-only-token"})
    assert client.get_product_import_status("import-123")["status"] == "FINISHED"
    assert client.get_product_import_result("import-123")["status"] == "FINISHED"
    assert "/products/import?i=import-123" in calls[0][0]
    assert "/products/import/result?i=import-123" in calls[1][0]
    assert all(method == "GET" for _, method in calls)


def test_kaspi_order_detail_and_entry_reads(monkeypatch):
    calls = []

    def request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        calls.append(url)
        if url.endswith("/entries?page%5Bnumber%5D=0&page%5Bsize%5D=1"):
            return 200, {"data": [{"id": "entry-1"}], "meta": {"pageCount": 2}}
        if url.endswith("/entries?page%5Bnumber%5D=1&page%5Bsize%5D=1"):
            return 200, {"data": [{"id": "entry-2"}], "meta": {"pageCount": 2}}
        return 200, {"data": {"id": "order-1"}}

    monkeypatch.setattr(connectors, "_json_request", request)
    client = KaspiConnector(account(), {"token": "server-only-token"})
    assert client.get_order("order-1")["data"]["id"] == "order-1"
    assert client.get_order_entries("order-1", page_size=1) == [{"id": "entry-1"}, {"id": "entry-2"}]
    assert "include%5Borders%5D=user" in calls[0]
    assert len(calls) == 3


def test_kaspi_sync_fetches_resumable_bounded_windows(monkeypatch):
    from datetime import datetime, timezone
    import json
    from urllib.parse import urlparse, parse_qs

    requests = []

    def request(url, headers, timeout=20, method="GET", payload=None, retries=2):
        requests.append(url)
        return 200, {"data": [], "meta": {"pageCount": 0}}

    monkeypatch.setattr(connectors, "_json_request", request)
    client = KaspiConnector(account(), {"token": "server-only-token"})
    first = client.fetch()
    assert first.records == []
    assert first.next_cursor
    cursor = json.loads(first.next_cursor)
    first_params = parse_qs(urlparse(requests[0]).query)
    first_start = int(first_params["filter[orders][creationDate][$ge]"][0])
    first_end = int(first_params["filter[orders][creationDate][$le]"][0])
    assert first_end - first_start <= 7 * 24 * 60 * 60 * 1000
    assert cursor["direction"] == "backward"
    assert cursor["start_ms"] < first_start

    second = client.fetch(first.next_cursor)
    assert second.records == []
    assert second.next_cursor
    second_params = parse_qs(urlparse(requests[1]).query)
    assert int(second_params["filter[orders][creationDate][$ge]"][0]) == cursor["start_ms"]
    assert int(second_params["filter[orders][creationDate][$le]"][0]) - cursor["start_ms"] <= 7 * 24 * 60 * 60 * 1000


def test_kaspi_sync_commits_each_window_and_clears_cursor(monkeypatch):
    from types import SimpleNamespace
    from app import main
    from app.connectors import SyncResult

    account_row = SimpleNamespace(id=17, company_id=4, channel="Kaspi", mode="api",
                                  sync_cursor="", sync_status="running", sync_error="", last_sync=None)
    class FakeDB:
        commits = 0
        def commit(self): self.commits += 1
        def flush(self): pass
        def get(self, model, key): return account_row
    db = FakeDB()

    class Worker:
        sections = []
        def __init__(self): self.cursors = []
        def fetch(self, cursor=None):
            self.cursors.append(cursor)
            if cursor is None:
                return SyncResult("kaspi", [{"external_id":"one"}], "window one", next_cursor="cursor-two")
            return SyncResult("kaspi", [{"external_id":"two"}], "window two", next_cursor=None)
    worker = Worker()
    monkeypatch.setattr(main, "load_saved_credentials", lambda *_: {})
    monkeypatch.setattr(main, "connector", lambda *_: worker)
    monkeypatch.setattr(main, "_stage_marketplace_records", lambda _db, _acc, result: (len(result.records), 0))
    projection_calls = []
    def project(_db, _user, _account, **kwargs):
        projection_calls.append(kwargs)
        return {"projected":1,"pending_erp":0}
    monkeypatch.setattr(main.marketplace_pipeline, "project_account", project)
    monkeypatch.setattr(main, "audit", lambda *_: None)

    result = main._perform_marketplace_sync(db, SimpleNamespace(), account_row)

    assert worker.cursors == [None, "cursor-two"]
    assert result["records"] == 2 and result["windows"] == 2
    assert result["incremental_projected"] == 3
    assert projection_calls[0].get("date_from") is not None
    assert projection_calls[1:] == [{"external_ids":["one"]},{"external_ids":["two"]},{}]
    assert account_row.sync_cursor == ""
    assert account_row.sync_status == "done"
    assert db.commits >= 3


def test_kaspi_unmapped_order_items_appear_in_catalog(client):
    from app.db import SessionLocal
    from app.models import MarketplaceRecord

    with SessionLocal() as db:
        db.add(MarketplaceRecord(account_id=1, company_id=1, source="kaspi",
            external_id="entry:order-1:entry-1", payload={
                "record_type":"order_entry","external_id":"entry:order-1:entry-1",
                "order_id":"order-1","entry_id":"entry-1","external_product_id":"product-1",
                "product_name":"Kaspi sample","sku":"SKU-1","quantity":2,"total_price":1500,
                "order_status":"COMPLETED","order_creation_date":1792530000000,
                "merchant_product_attributes":{"name":"Kaspi sample","brand":"Brand","imageUrl":"https://cdn.example.kz/kaspi-sample.jpg"}}))
        db.commit()

    response = client.get("/api/marketplace-products", params={"channel":"Kaspi"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Kaspi sample"
    assert body["items"][0]["sku"] == "SKU-1"
    assert body["items"][0]["sold_units"] == 2
    assert body["items"][0]["source"] == "Kaspi order items"
    assert body["items"][0]["image_url"] == "https://cdn.example.kz/kaspi-sample.jpg"


def test_kaspi_images_nested_in_merchant_attributes_are_imported_to_product_media():
    from app.marketplace_pipeline import _media_urls

    assert _media_urls({"merchant_product_attributes": {
        "images": [{"url": "https://cdn.example.kz/front.jpg"}],
        "imageUrl": "https://cdn.example.kz/main.jpg",
    }}) == ["https://cdn.example.kz/main.jpg", "https://cdn.example.kz/front.jpg"]


def test_stale_kaspi_status_starts_only_one_automatic_resume(client, monkeypatch):
    from app import main
    from app.db import SessionLocal
    from app.models import Account

    with SessionLocal() as db:
        account_row = db.get(Account, 1)
        account_row.sync_status = "failed"
        account_row.sync_error = "SYNC_TIMEOUT: old sync was interrupted"
        db.commit()
    started = []
    monkeypatch.setattr(main, "_background_marketplace_sync",
                        lambda account_id, user_id: started.append((account_id, user_id)))

    response = client.get("/api/accounts/1/sync-status")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    assert response.json()["error"].startswith("SYNC_RECOVERY_STARTED")
    assert started == [(1, 1)]


def test_timed_out_kaspi_recovery_is_not_restarted_forever(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app import main
    from app.db import SessionLocal
    from app.models import Account

    with SessionLocal() as db:
        account_row = db.get(Account, 1)
        account_row.sync_status = "running"
        account_row.sync_error = "SYNC_RECOVERY_STARTED: attempt=2"
        account_row.last_sync = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    started = []
    monkeypatch.setattr(main, "_background_marketplace_sync",
                        lambda account_id, user_id: started.append((account_id, user_id)))

    response = client.get("/api/accounts/1/sync-status")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert "attempt=2" in response.json()["error"]
    assert started == []



def test_stale_first_kaspi_recovery_starts_second_and_only_second_attempt(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app import main
    from app.db import SessionLocal
    from app.models import Account

    with SessionLocal() as db:
        account_row = db.get(Account, 1)
        account_row.sync_status = "running"
        account_row.sync_error = "SYNC_RECOVERY_STARTED: attempt=1"
        account_row.last_sync = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    started = []
    monkeypatch.setattr(main, "_background_marketplace_sync",
                        lambda account_id, user_id: started.append((account_id, user_id)))

    response = client.get("/api/accounts/1/sync-status")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    assert "attempt=2" in response.json()["error"]
    assert started == [(1, 1)]



def test_health_matches_current_alembic_head(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "migration": "compatible",
    }
