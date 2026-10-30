import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from app import connectors, main
from app.connectors import KaspiConnector, AccessRequired, SyncResult
from app.kaspi_integrity import source_quality, period_key


def test_strict_scan_reads_every_page_state_and_week_without_skipping(monkeypatch):
    calls = []
    def request(url, headers, **kw):
        q = parse_qs(urlparse(url).query)
        state = q["filter[orders][state]"][0]
        page = int(q["page[number]"][0])
        lo, hi = [int(q[k][0]) for k in ("filter[orders][creationDate][$ge]", "filter[orders][creationDate][$le]")]
        assert hi-lo < 7*86400000
        calls.append((lo, hi, state, page))
        # 101 orders force pagination; known verified entries avoid detail calls.
        data = [{"id":str(i), "attributes":{"code":str(i),"status":"CANCELLED"}} for i in range(100 if page == 0 else 1)] if state == "ARCHIVE" else []
        return 200, {"data":data, "meta":{"pageCount":2 if state == "ARCHIVE" else 0}}
    monkeypatch.setattr(connectors, "_json_request", request)
    cursor = json.dumps({"_qor_kaspi_cursor":1,"scope":"status_only","scan_version":3,
        "start_ms":1000,"until_ms":8*86400000,"event_start_ms":1000,"event_end_ms":8*86400000,
        "known_entry_counts":{str(i):1 for i in range(100)}})
    seen = 0
    for _ in range(200):
        result = KaspiConnector(SimpleNamespace(mode="api"), {"token":"x"}).fetch(cursor)
        seen += sum(r["record_type"] == "order" for r in result.records)
        cursor = result.next_cursor
        if cursor is None:
            break
    else:
        pytest.fail("scan did not terminate")
    assert seen == 202
    assert {x[2] for x in calls} == {"ARCHIVE","NEW","SIGN_REQUIRED","PICKUP","DELIVERY","KASPI_DELIVERY"}
    windows = sorted(set((x[0],x[1]) for x in calls))
    assert windows[0][0] == 1000 and windows[-1][1] == 8*86400000
    assert windows[0][1]+1 == windows[1][0]


def test_empty_middle_page_cannot_certify_completion(monkeypatch):
    monkeypatch.setattr(connectors,"_json_request",lambda *a,**k:(200,{"data":[],"meta":{"pageCount":3}}))
    with pytest.raises(AccessRequired,match="пустая страница"):
        KaspiConnector(SimpleNamespace(mode="api"),{"token":"x"}).fetch(json.dumps({
            "_qor_kaspi_cursor":1,"scope":"period","scan_version":3,"start_ms":1,"until_ms":1000,"page":1}))


def test_detail_lookup_fills_missing_date_and_preserves_return_unknown(monkeypatch):
    issued = 1792627200000
    def request(url, headers, **kw):
        if "/entries?" in url:
            return 200,{"data":[{"id":"e","attributes":{"quantity":2,"totalPrice":1000,"offer":{"code":"A","name":"Item"}}}],"meta":{"pageCount":1}}
        if "code%5D" in url:
            return 200,{"data":[{"id":"o","attributes":{"completionDate":issued}}]}
        return 200,{"data":[{"id":"o","attributes":{"code":"O","status":"RETURNED"}}],"meta":{"pageCount":1}}
    monkeypatch.setattr(connectors,"_json_request",request)
    result=KaspiConnector(SimpleNamespace(mode="api"),{"token":"x"}).fetch(json.dumps({
        "_qor_kaspi_cursor":1,"scope":"status_only","scan_version":3,"start_ms":1,"until_ms":issued+1}))
    order=next(x for x in result.records if x["record_type"]=="order")
    assert order["completion_date"]==issued
    assert order["returned_date"] is None
    assert order["entries_complete"] and order["entries_count"]==1
    assert next(x for x in result.records if x["record_type"]=="order_entry")["quantity"]==2


def test_coverage_of_another_period_never_means_complete():
    account=SimpleNamespace(id=1,integration_settings={"kaspi_period_sync":{period_key("issued",date(2026,10,1),date(2026,10,31)):"ok"}})
    quality=source_quality([account],[],date(2026,7,8),date(2026,9,25))
    assert not quality["coverage_complete"]


def test_complete_period_requires_verified_entries_and_identity():
    start,end=date(2026,7,8),date(2026,9,25)
    account=SimpleNamespace(id=1,integration_settings={"kaspi_period_sync":{period_key("issued",start,end):"ok"}})
    rows=[(1,{"record_type":"order","order_id":"o","status":"COMPLETED","completion_date":1784000000000,
              "entries_complete":True,"entries_count":1}),
          (1,{"record_type":"order_entry","order_id":"o","sku":"A","quantity":1,"total_price":100})]
    assert source_quality([account],rows,start,end)["data_complete"]
    rows[1][1]["sku"]=""
    assert not source_quality([account],rows,start,end)["data_complete"]


def test_unknown_return_date_is_a_quality_failure_even_with_complete_coverage():
    start,end=date(2026,7,8),date(2026,9,25)
    account=SimpleNamespace(id=1,integration_settings={"kaspi_period_sync":{period_key("issued",start,end):"ok"}})
    quality=source_quality([account],[(1,{"record_type":"order","order_id":"o","status":"RETURNED","completion_date":1784000000000,"entries_complete":True,"entries_count":1}),
        (1,{"record_type":"order_entry","order_id":"o","quantity":1,"total_price":100})],start,end)
    assert quality["coverage_complete"] and not quality["data_complete"]
    assert quality["issues"]["missing_return_date"]==1


def test_background_job_checkpoints_and_resumes_failed_page(client,monkeypatch):
    from app.db import SessionLocal
    from app.models import Account
    start,end=date(2026,7,8),date(2026,9,25)
    key=period_key("issued",start,end)
    with SessionLocal() as db:
        account=db.get(Account,1)
        account.sync_status="running";account.sync_error="KASPI_PERIOD_SYNC:test"
        account.integration_settings={"kaspi_period_job":{"start":str(start),"end":str(end),"mode":"issued","user_id":1,"status":"running"}}
        db.commit()
    cursors=[]
    resume=json.dumps({"_qor_kaspi_cursor":1,"scope":"status_only","scan_version":3,"page":2,"start_ms":1,"until_ms":2000})
    class Worker:
        def fetch(self,cursor):
            cursors.append(cursor)
            if len(cursors)==1:
                return SyncResult("kaspi",[],"page",next_cursor=resume)
            raise AccessRequired("temporary API failure")
    monkeypatch.setattr(main,"connector",lambda *a:Worker())
    monkeypatch.setattr(main,"load_saved_credentials",lambda *a:{"token":"x"})
    main._background_kaspi_period_sync(1,1,start,end,[],status_only=True)
    with SessionLocal() as db:
        account=db.get(Account,1)
        assert account.integration_settings["kaspi_period_progress"][key]==resume
        assert account.integration_settings["kaspi_period_job"]["status"]=="retry"
        assert key not in account.integration_settings.get("kaspi_period_sync",{})
        account.sync_error="KASPI_PERIOD_SYNC:retry";db.commit()
    class Success:
        def fetch(self,cursor):
            assert cursor==resume
            return SyncResult("kaspi",[],"done")
    monkeypatch.setattr(main,"connector",lambda *a:Success())
    main._background_kaspi_period_sync(1,1,start,end,[],status_only=True)
    with SessionLocal() as db:
        account=db.get(Account,1)
        assert account.sync_status=="done"
        assert key in account.integration_settings["kaspi_period_sync"]
        assert key not in account.integration_settings["kaspi_period_progress"]


def test_stale_worker_cannot_write_after_lease_is_replaced(client,monkeypatch):
    from app.db import SessionLocal
    from app.models import Account
    monkeypatch.setattr(main,"load_saved_credentials",lambda *a:{})
    with SessionLocal() as db:
        a=db.get(Account,1);a.sync_error="KASPI_PERIOD_SYNC:new";db.commit()
    monkeypatch.setattr(main,"connector",lambda *a:SimpleNamespace(fetch=lambda c:pytest.fail("stale worker executed")))
    main._background_kaspi_period_sync(1,1,date(2026,7,8),date(2026,9,25),[],expected_lease="KASPI_PERIOD_SYNC:old")


def test_configured_backfill_is_targeted_and_queued_once(client,monkeypatch):
    from app.db import SessionLocal
    from app.models import Account
    monkeypatch.setenv("KASPI_BACKFILL_ACCOUNT_IDS","1")
    monkeypatch.setenv("KASPI_BACKFILL_START","2026-07-08")
    monkeypatch.setenv("KASPI_BACKFILL_END","2026-09-25")
    calls=[]
    monkeypatch.setattr(main,"_background_kaspi_period_sync",lambda *args:calls.append(args))
    main._resume_kaspi_jobs_once()
    main._resume_kaspi_jobs_once()
    assert len(calls)==1
    assert calls[0][:4]==(1,1,date(2026,7,8),date(2026,9,25))
    with SessionLocal() as db:
        assert db.get(Account,1).integration_settings["kaspi_period_job"]["status"]=="running"
        assert not db.get(Account,2).integration_settings


def test_summary_uses_completion_date_for_return_missing_event_date(client):
    from app.db import SessionLocal
    from app.models import Account,MarketplaceRecord
    with SessionLocal() as db:
        a=db.get(Account,1);a.sync_status="done"
        db.add(MarketplaceRecord(account_id=1,company_id=1,source="kaspi",external_id="entry:o:e",
            payload={"record_type":"order_entry","order_id":"o","order_status":"RETURNED",
                     "quantity":1,"total_price":100,"completed_date":1784000000000}))
        db.commit()
    result=client.get("/api/marketplace-summary?channel=Kaspi&account_id=1&start=2026-07-08&end=2026-09-25").json()
    assert result["api_return_units"]==1
    assert result["api_undated_return_units"]==1
    assert result["api_unconverted"]==0
    assert result["source_complete"] is False
