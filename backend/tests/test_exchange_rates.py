from datetime import date
from decimal import Decimal
from app import exchange_rates
from app.models import ExchangeRate
from app.db import SessionLocal


def test_parse_nbk_rub_nominal():
    xml='''<rates><item><title>RUB</title><description>5.37</description><quant>1</quant></item><item><title>UZS</title><description>3.87</description><quant>100</quant></item></rates>'''
    assert exchange_rates.parse_nbk_xml(xml, 'RUB') == Decimal('5.37')
    assert exchange_rates.parse_nbk_xml(xml, 'UZS') == Decimal('0.0387')


def test_historical_rate_is_cached(monkeypatch):
    db=SessionLocal()
    calls=[]
    def fake(currency, on_date, timeout=8.0):
        calls.append((currency,on_date)); return Decimal('5.37')
    monkeypatch.setattr(exchange_rates, 'fetch_nbk_rate', fake)
    d=date(2026,10,6)
    assert exchange_rates.rate_scaled(db,'RUB',d)[0] == 53700
    assert exchange_rates.rate_scaled(db,'RUB',d)[1] == 'NBK'
    db.commit()
    monkeypatch.setattr(exchange_rates, 'fetch_nbk_rate', lambda *a,**k: (_ for _ in ()).throw(Exception('offline')))
    assert exchange_rates.rate_scaled(db,'RUB',d)[0] == 53700
    assert db.query(ExchangeRate).filter_by(currency='RUB', rate_date=d).count() == 1
    db.close()
