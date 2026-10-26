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
