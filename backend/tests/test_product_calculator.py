from decimal import Decimal
from app.ai import calculator

def test_full_cost_and_profit_are_deterministic():
    r = calculator({"quantity":100,"purchase_price":10,"fx_rate":50,"price":1000,"delivery":10000,"customs":5000,"commission_percent":10,"marketplace_logistics_unit":20,"advertising_percent":5,"return_percent":0})
    assert r["full_cost_total"] == "65000.00"
    assert r["full_cost_unit"] == "650.00"
    assert r["cogs"] == "65000.00"
    assert r["net_profit"] == "18000.00"

def test_returns_do_not_expense_unsold_inventory():
    r = calculator({"quantity":100,"purchase_price":500,"fx_rate":1,"price":1000,"return_percent":20})
    assert r["expected_sold_units"] == "80.00"
    assert r["cogs"] == "40000.00"
    assert r["full_cost_total"] == "50000.00"

def test_turnover_not_invented_without_demand_data():
    r = calculator({"quantity":10,"purchase_price":100,"price":200})
    assert r["turnover"] is None
    assert "нужны" in r["turnover_notice"]
