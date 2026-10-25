"""Official FX rates for ERP posting.

NBK is the primary source. Rates are cached by effective date so historical
marketplace postings never change when today's market moves. Manual account FX
remains a fallback when the official service is temporarily unavailable.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import xml.etree.ElementTree as ET
import httpx
from sqlalchemy import select
from .models import ExchangeRate, AccountExchangeRate

NBK_DATE_URL = "https://nationalbank.kz/rss/get_rates.cfm"

class FxUnavailable(RuntimeError):
    pass


def _parse_decimal(value):
    try:
        return Decimal(str(value).strip().replace(',', '.'))
    except (InvalidOperation, TypeError, ValueError):
        return None


def parse_nbk_xml(content: str, currency: str):
    """Return KZT for one unit of currency from NBK XML (handles nominal units)."""
    root = ET.fromstring(content)
    wanted = currency.upper()
    for item in root.iter():
        children = {c.tag.split('}')[-1].lower(): (c.text or '').strip() for c in list(item)}
        code = children.get('title') or children.get('code') or children.get('charcode')
        if (code or '').upper() != wanted:
            continue
        value = _parse_decimal(children.get('description') or children.get('rate') or children.get('value'))
        nominal = _parse_decimal(children.get('quant') or children.get('nominal') or '1') or Decimal(1)
        if value is not None and nominal > 0:
            return value / nominal
    raise FxUnavailable(f'NBK_RATE_NOT_FOUND:{wanted}')


def fetch_nbk_rate(currency: str, on_date: date, timeout=8.0):
    if currency.upper() == 'KZT':
        return Decimal('1')
    params = {'fdate': on_date.strftime('%d.%m.%Y')}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(NBK_DATE_URL, params=params)
        response.raise_for_status()
    return parse_nbk_xml(response.text, currency)


def rate_scaled(db, currency: str, on_date: date, acc=None):
    """Return KZT/unit scaled by 10,000, cached by currency+date.

    Official historical rate wins. If NBK is unavailable, an account manual rate
    is used only when its currency matches, preserving current offline behavior.
    """
    currency = (currency or 'KZT').upper()
    if currency == 'KZT':
        return 10000, 'identity'
    cached = db.scalar(select(ExchangeRate).where(
        ExchangeRate.currency == currency, ExchangeRate.rate_date == on_date))
    if cached:
        return cached.rate_scaled, cached.source
    if acc:
        manual=db.scalar(select(AccountExchangeRate).where(AccountExchangeRate.account_id==acc.id,
            AccountExchangeRate.currency==currency,AccountExchangeRate.rate_date==on_date))
        if manual: return manual.rate_scaled,manual.source
    try:
        value = fetch_nbk_rate(currency, on_date)
        scaled = int((value * Decimal(10000)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        if scaled <= 0:
            raise FxUnavailable('NBK_RATE_INVALID')
        db.add(ExchangeRate(currency=currency, rate_date=on_date, rate_scaled=scaled, source='NBK'))
        db.flush()
        return scaled, 'NBK'
    except Exception:
        raise FxUnavailable('FX_REQUIRED:' + currency)
