from app.db import SessionLocal
from app.models import Account, Expense, business_today


def test_expenses_summary_groups_by_channel_and_category_including_archived_accounts(client):
    today = business_today()
    with SessionLocal() as db:
        wb = Account(company_id=1, name="WB архив", channel="Wildberries", mode="api", active=False)
        db.add(wb)
        db.flush()
        db.add_all([
            Expense(company_id=1, account_id=1, reference="KASPI-LOG-TEST", date=today,
                    category="Marketplace logistics", amount=1300),
            Expense(company_id=1, account_id=wb.id, reference="WB-FINE-TEST", date=today,
                    category="Marketplace penalties", amount=2000),
            Expense(company_id=1, account_id=None, reference="OFFLINE-RENT-TEST", date=today,
                    category="Аренда", amount=500),
        ])
        db.commit()

    response = client.get(f"/api/expenses/summary?start={today}&end={today}")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["posted_total"] == 3800
    channels = {row["channel_label"]: row for row in summary["channels"]}
    assert channels["Kaspi"]["posted_total"] == 1300
    assert channels["Wildberries"]["posted_total"] == 2000
    assert channels["Офлайн"]["posted_total"] == 500
    categories = {row["category"]: row for row in summary["categories"]}
    assert categories["Логистика"]["posted_total"] == 1300
    assert categories["Штрафы"]["posted_total"] == 2000
    assert categories["Аренда"]["posted_total"] == 500


def test_expenses_operations_streams_and_preserves_pagination(client):
    from app.models import Sale

    today = business_today()
    with SessionLocal() as db:
        db.add_all([
            Expense(company_id=1, account_id=1, reference="EXP-OPS-KASPI-TEST", date=today,
                    category="Marketplace commission", amount=500),
            Expense(company_id=1, account_id=None, reference="EXP-OPS-OFFLINE-TEST", date=today,
                    category="Аренда", amount=200),
            Expense(company_id=1, account_id=3, reference="EXP-OPS-B2B-TEST", date=today,
                    category="Marketplace logistics", amount=125),
            Sale(company_id=1, account_id=1, product_id=1, reference="EXP-OPS-SALE-TEST",
                 date=today, quantity=1, revenue=10000, cogs=0, cogs_pending=True,
                 commission=300, logistics=120, advertising=80),
        ])
        db.commit()

    params = {"start": str(today), "end": str(today), "limit": 2}
    pages = []
    for offset in (0, 2, 4):
        response = client.get("/api/expenses/operations", params={**params, "offset": offset})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 6
        pages.extend(payload["items"])

    expected = sorted(
        pages,
        key=lambda row: (row["date"], row["record_id"], row["key"]),
        reverse=True,
    )
    assert pages == expected
    assert len({row["key"] for row in pages}) == 6

    kaspi = client.get(
        "/api/expenses/operations",
        params={"start": str(today), "end": str(today), "channel": "Kaspi"},
    )
    assert kaspi.status_code == 200, kaspi.text
    assert kaspi.json()["total"] == 4
    assert all(row["channel"] == "Kaspi" for row in kaspi.json()["items"])

    other_company = client.get(
        "/api/expenses/operations",
        params={"start": str(today), "end": str(today), "company_id": 2},
    )
    assert other_company.status_code == 200, other_company.text
    assert other_company.json()["total"] == 0
