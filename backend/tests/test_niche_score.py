from app import ai


def test_niche_requires_all_seven_dimensions():
    result = ai.niche_score({"monthly_demand": 1000})
    assert result["score"] is None
    assert result["decision"] == "Данные недостаточны"
    assert "competitors" in result["missing"]


def test_niche_score_has_required_dimensions_and_decision():
    result = ai.niche_score({
        "monthly_demand": 1200, "competitors": 8, "margin_percent": 38,
        "advertising_percent": 8, "seasonality_risk": 15,
        "logistics_percent": 7, "return_percent": 4, "rating": 4.6,
    })
    assert 0 <= result["score"] <= 100
    assert set(result["components"]) == {"demand", "competition", "margin", "advertising", "seasonality", "logistics", "risk"}
    assert result["decision"] in {"Кіруге ұсынылады", "Кіруге ұсынылмайды"}


def test_niche_score_does_not_invent_missing_market_data():
    result = ai.niche_score({
        "monthly_demand": 1200, "competitors": 8, "margin_percent": 38,
        "advertising_percent": 8, "seasonality_risk": 15,
        "logistics_percent": 7,
    })
    assert result["score"] is None
    assert "return_percent" in result["missing"]
