from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"

def test_accounting_models_exist():
    text = (ROOT / "models.py").read_text()
    for name in ("Counterparty", "BankTransaction", "TaxRule", "GeneratedDocument"):
        assert f"class {name}" in text

def test_tax_requires_accountant_approval_field():
    text = (ROOT / "models.py").read_text()
    assert "accountant_approved" in text
    assert "rate_bps >= 0 AND rate_bps <= 10000" in text

def test_accounting_summary_warns_about_review():
    text = (ROOT / "main.py").read_text()
    assert "/api/accounting/summary" in text
    assert "требует проверки бухгалтером" in text
