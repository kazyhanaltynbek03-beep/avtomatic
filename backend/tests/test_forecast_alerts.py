from app import ai


def snap(days=14, active=10):
    return {"start":"2026-09-01", "end":f"2026-09-{days:02d}", "revenue":1_400_000, "net_profit":280_000,
            "units":140, "daily":[{"date":f"2026-09-{i:02d}","revenue":100_000 if i <= active else 0} for i in range(1,days+1)],
            "stock":[{"product_id":1,"name":"SKU A","quantity":50,"sold":140,"unit_cost":1000}]}


def test_forecast_is_deterministic_and_has_confidence():
    r=ai.forecast(snap())
    assert r["status"] == "ok"
    assert r["revenue"] == 3_000_000
    assert r["net_profit"] == 600_000
    assert 0 < r["confidence"] <= 90
    assert r["reorder"][0]["stockout_risk"] is True


def test_forecast_refuses_short_history():
    s=snap(); s["start"]="2026-09-10"; s["end"]="2026-09-14"; s["daily"]=s["daily"][:5]
    r=ai.forecast(s)
    assert r["status"] == "insufficient_data"
    assert r["confidence"] == 0
