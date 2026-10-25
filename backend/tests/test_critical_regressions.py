from .conftest import buy, sell, post, report


def test_dashboard_uses_wildberries_channel_name(client):
    account = client.post("/api/data/accounts", json={
        "company_id": 1, "name": "WB Main", "channel": "Wildberries"
    })
    assert account.status_code == 200, account.text
    buy(client, qty=2)
    sell(client, ref="WB-1", qty=1, price=3000, account=account.json()["id"])
    dashboard = client.get("/api/dashboard/summary", params={
        "start": "2026-10-01", "end": "2026-10-31"
    })
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["selected"]["channels"]["Wildberries"] == 3000
    assert dashboard.json()["selected"]["channels"]["WB"] == 3000


def test_stock_days_and_fx_purchase_cost_are_deterministic(client):
    post(client, "purchases", company_id=1, reference="CNY-1", supplier="CN", date="2026-10-01",
         lines=[{"product_id": 1, "quantity": 2, "unit_cost": 2000, "currency": "CNY", "fx_rate": 700000}])
    sell(client, ref="S-FX", qty=1, price=200000, day="2026-10-02")
    stock = report(client)["stock"][0]
    assert stock["value"] == 140000
    assert stock["days_of_stock"] == 31.0
    assert stock["turnover_days"] == 31.0


def test_audit_keeps_before_and_after_values(client):
    item = client.post("/api/data/products", json={"sku": "AUDIT", "name": "Before"}).json()
    changed = client.put("/api/data/products/" + str(item["id"]), json={"sku": "AUDIT", "name": "After"})
    assert changed.status_code == 200, changed.text
    rows = client.get("/api/data/audit").json()["items"]
    audit = next(x for x in rows if x["action"] == "update" and x["entity"] == "products")
    assert audit["details"]["before"]["name"] == "Before"
    assert audit["details"]["after"]["name"] == "After"
