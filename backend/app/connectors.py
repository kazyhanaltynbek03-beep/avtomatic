"""Marketplace connector boundary. Secrets stay server-side and production calls are never simulated."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import base64
import hashlib
import time
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from .models import IntegrationSecret
from urllib.parse import urlencode, quote
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError



def load_saved_credentials(db, account_id):
    row = db.scalar(select(IntegrationSecret).where(IntegrationSecret.account_id == account_id))
    if not row: return {}
    material = os.getenv("CREDENTIAL_ENCRYPTION_KEY")
    if not material:
        if os.getenv("APP_ENV", "development").lower() == "production":
            raise AccessRequired("Сервер интеграций не настроен: отсутствует CREDENTIAL_ENCRYPTION_KEY")
        material = os.getenv("OWNER_PASSWORD") or os.getenv("DATABASE_URL", "qor-local-dev")
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())
    try:
        return json.loads(Fernet(key).decrypt(row.encrypted_payload.encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        # Do not silently turn an encrypted-but-unreadable secret into an empty
        # credential set: that makes the downstream marketplace 401 look like a
        # bad seller token when the actual problem is the server encryption key.
        raise AccessRequired(
            "Не удалось расшифровать сохранённый токен интеграции. "
            "Проверьте CREDENTIAL_ENCRYPTION_KEY в Render и сохраните токен заново."
        ) from exc

@dataclass
class SyncResult:
    source: str
    records: list
    message: str
    next_cursor: str | None = None
    warnings: list | None = None


class AccessRequired(RuntimeError):
    pass


class Connector(ABC):
    provider = "generic"
    def __init__(self, account, credentials=None):
        self.account = account
        self.credentials = credentials or {}
    def required_secret_names(self): return []
    def connection_status(self):
        required = self.required_secret_names()
        missing = [name for name in required if not self.credentials.get(name)]
        return {"provider": self.provider, "mode": self.account.mode, "configured": not missing, "missing": missing, "live": self.account.mode == "api" and not missing}
    def test_connection(self):
        """Small bounded credential check; never trigger a full historical sync."""
        if self.connection_status()["missing"]:
            raise AccessRequired(f"{self.provider} credentials отсутствуют")
        return {"message": f"{self.provider}: credentials сохранены", "records_checked": 0}
    @abstractmethod
    def fetch(self, cursor=None) -> SyncResult: ...


def _retry_delay(headers, default=1):
    value = (headers or {}).get('Retry-After')
    if value:
        try: return min(180, max(1, float(value)))
        except (TypeError, ValueError):
            try: return min(180, max(1, (parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError): pass
    return default


def _json_request(url, headers, timeout=20, method="GET", payload=None, retries=2):
    """Make a bounded, secret-safe request with transient retry/backoff.

    Marketplace response bodies are intentionally never included in exceptions:
    providers may reflect request metadata, and those errors are rendered in the UI.
    """
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url, data=body, headers={**headers, "User-Agent": "QOR-AI-Business-ERP/1.0"}, method=method)
    for attempt in range(retries + 1):
        try:
            with urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return response.status, json.loads(raw) if raw else {}
        except HTTPError as exc:
            if exc.code in (401, 403):
                if "finance-api.wildberries.ru" in url:
                    raise AccessRequired(
                        "Wildberries Finance API отклонил токен или доступ к финансовым отчётам. "
                        "Проверьте актуальность токена и права финансовой аналитики."
                    )
                if "wildberries.ru" in url:
                    raise AccessRequired(
                        "Wildberries API отклонил токен или права доступа. "
                        "Проверьте токен и разрешения для этого раздела."
                    )
                raise AccessRequired("API отклонил ключ или недостаточно прав доступа.")
            if exc.code == 400 and "kaspi.kz" in url:
                # Keep the provider response body private; surface a useful,
                # non-secret explanation instead of the generic marketplace code.
                raise AccessRequired(
                    "Kaspi отклонил параметры запроса выбранного периода (HTTP 400). "
                    "Последние подтверждённые данные сохранены."
                )
            if exc.code == 429 and attempt < retries:
                time.sleep(_retry_delay(exc.headers, 60 if "wildberries.ru" in url else 1))
                continue
            if exc.code >= 500 and attempt < retries:
                time.sleep(0.25 * (2**attempt))
                continue
            if exc.code == 429:
                raise AccessRequired("Marketplace временно ограничил запросы. Повторите синхронизацию позже.")
            if exc.code >= 500:
                raise AccessRequired("Marketplace временно недоступен. Повторите синхронизацию позже.")
            raise AccessRequired("Marketplace отклонил запрос. Проверьте настройки интеграции.")
        except (URLError, TimeoutError):
            if attempt < retries:
                time.sleep(0.25 * (2**attempt))
                continue
            raise AccessRequired("Не удалось связаться с Marketplace. Проверьте сеть и повторите попытку.")
        except json.JSONDecodeError:
            raise AccessRequired("Marketplace вернул ответ в неожиданном формате.")


class KaspiConnector(Connector):
    provider = "Kaspi"
    base_url = "https://kaspi.kz/shop/api/v2/orders"
    def required_secret_names(self): return ["token"]
    def _headers(self):
        return {"Content-Type":"application/vnd.api+json","Accept":"application/vnd.api+json","X-Auth-Token":str(self.credentials.get("token") or "").strip()}
    def test_connection(self):
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        # Official Kaspi pagination accepts page 0 and a maximum page size of
        # 100. One row validates the token without loading the business history.
        _, payload = _json_request(self.base_url + "?" + urlencode({"page[number]":0,"page[size]":1}), self._headers(), timeout=12, retries=1)
        return {"message":"Kaspi: подключение подтверждено", "records_checked":len(payload.get("data") or [])}
    def fetch(self, cursor=None):
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        # Process only ten orders per call so the coordinator can commit and
        # checkpoint before requesting more remote details.
        now = datetime.now(timezone.utc)
        state = {}
        if cursor:
            try:
                candidate = json.loads(cursor)
                if isinstance(candidate, dict) and candidate.get("_qor_kaspi_cursor") == 1:
                    state = candidate
            except (TypeError, ValueError):
                pass
        status_only = state.get("scope") == "status_only"
        period_mode = state.get("scope") in {"period", "status_only"}
        period_scope = "status_only" if status_only else "period"
        history_start = now - timedelta(days=370)
        # Legacy cursors were created by oldest-first syncs. Restart those from
        # the latest week; previously imported rows are upserted by external ID.
        if state and not state.get("direction") and not period_mode:
            state = {}
        # New syncs start with the latest week so the current dashboard is useful
        # immediately, then walk backwards through a full reporting year.
        direction = state.get("direction") or "backward"
        until = datetime.fromtimestamp(state["until_ms"] / 1000, timezone.utc) if state.get("until_ms") else now
        window_start = (datetime.fromtimestamp(state["start_ms"] / 1000, timezone.utc)
                        if state.get("start_ms") else max(history_start, now - timedelta(days=7)))
        page = max(0, int(state.get("page") or 0))
        offset = max(0, int(state.get("offset") or 0))
        window_end = (until if status_only else min(window_start + timedelta(days=7) - timedelta(milliseconds=1), until))
        params = {"page[number]": page, "page[size]": 10 if period_mode else 100,
            "filter[orders][creationDate][$ge]": int(window_start.timestamp()*1000),
            "filter[orders][creationDate][$le]": int(window_end.timestamp()*1000),
            **({} if period_mode else {"include[orders]": "user"})}
        if status_only:
            payload = {"data":[],"meta":{"pageCount":0}}
        else:
            _, payload = _json_request(self.base_url + "?" + urlencode(params), self._headers())
        data = payload.get("data") or []
        selected = data[offset:offset+10]
        extras_selected = False
        extras_requested = 0
        missing_errors = []
        if period_mode and not selected:
            page_count = (payload.get("meta") or {}).get("pageCount")
            no_more_pages = not data or (page_count is not None and page >= int(page_count))
            # Finish every selected-date chunk before refreshing older orders.
            if no_more_pages and (status_only or window_end >= until):
                extra_ids = state.get("extra_ids") or []
                extra_offset = max(0, int(state.get("extra_offset") or 0))
                extra_batch = extra_ids[extra_offset:extra_offset+10]
                extras_requested = len(extra_batch)
                if extra_batch:
                    selected = []
                    for code in extra_batch:
                        _, detail = _json_request(self.base_url + "?" + urlencode({"filter[orders][code]":str(code)}), self._headers())
                        items = detail.get("data") or []
                        selected.extend(items[:1])
                        if not items:
                            missing_errors.append(f"Kaspi: заказ с code={code} не найден при обновлении статуса")
                    extras_selected = True
        records = {}; errors = missing_errors; pages = 1
        included = payload.get("included") or []
        for item in selected:
            a = item.get("attributes") or {}
            oid = str(item.get("id") or a.get("code") or "")
            if not oid:
                raise AccessRequired("Kaspi: заказ без устойчивого идентификатора")
            order = {"external_id": "order:"+oid, "record_type": "order", "order_id": oid,
                "code": a.get("code"), "total_price": a.get("totalPrice"),
                "delivery_cost_for_seller": a.get("deliveryCostForSeller"),
                "delivery_cost_for_buyer": a.get("deliveryCost"),
                "delivery_mode": a.get("deliveryMode"),
                "is_kaspi_delivery": a.get("isKaspiDelivery"),
                "cancellation_reason": a.get("cancellationReason") or a.get("cancelReason"),
                "state": a.get("state"), "status": a.get("status"),
                "creation_date": a.get("creationDate"), "completion_date": a.get("completionDate"), "returned_date": a.get("returnedDate") or a.get("returnDate"), "return_delivery_cost_for_seller": a.get("returnDeliveryCostForSeller"), "raw_attributes": a}
            relationship = ((item.get("relationships") or {}).get("user") or {}).get("data") or {}
            customer_obj = next((x for x in included
                if x.get("type") == relationship.get("type") and str(x.get("id")) == str(relationship.get("id"))), {})
            order["customer"] = customer_obj.get("attributes") or (a.get("customer") or {})
            records[order["external_id"]] = order
            # Kaspi's official order API exposes seller delivery cost at order
            # level. Keep it as a separate idempotent financial staging event;
            # buyer delivery cost is retained for display and never expensed.
            seller_delivery = a.get("deliveryCostForSeller")
            if seller_delivery is not None:
                delivery_id = "delivery:" + oid
                records[delivery_id] = {
                    "external_id": delivery_id, "record_type": "delivery_charge",
                    "order_id": oid, "amount": seller_delivery, "currency": "KZT",
                    "order_status": a.get("status"), "order_state": a.get("state"),
                    "order_creation_date": a.get("creationDate"),
                    "completed_date": a.get("completionDate"),
                    "delivery_mode": a.get("deliveryMode"),
                    "is_kaspi_delivery": a.get("isKaspiDelivery"),
                }
            return_delivery = a.get("returnDeliveryCostForSeller")
            if return_delivery not in (None, "", 0, 0.0, "0"):
                records["return-delivery:" + oid] = {
                    "external_id": "return-delivery:" + oid, "record_type": "return_delivery_charge",
                    "order_id": oid, "amount": return_delivery, "currency": "KZT",
                    "order_status": a.get("status"), "returned_date": a.get("returnedDate") or a.get("returnDate"),
                    "order_creation_date": a.get("creationDate"), "completion_date": a.get("completionDate"),
                    "raw_attributes": a,
                }
            try:
                entry_page = 0
                while True:
                    url = f"{self.base_url}/{quote(oid, safe='')}/entries?" + urlencode({"page[number]": entry_page, "page[size]":100})
                    _, ep = _json_request(url, self._headers())
                    entries = ep.get("data") or []
                    for entry in entries:
                        ea = entry.get("attributes") or {}; eid = str(entry.get("id") or "")
                        if not eid:
                            raise AccessRequired("Kaspi: позиция без идентификатора")
                        product = {}; merchant = {}; mapping_error = ''
                        try:
                            _, pp = _json_request("https://kaspi.kz/shop/api/v2/orderentries/" + quote(eid, safe='') + "/product", self._headers())
                            product = pp.get('data') or {}
                            if product.get('id'):
                                _, mp = _json_request("https://kaspi.kz/shop/api/v2/masterproducts/" + quote(str(product['id']), safe='') + "/merchantProduct", self._headers())
                                merchant = mp.get('data') or {}
                        except AccessRequired as exc:
                            mapping_error = str(exc)
                            errors.append('product:'+eid+': '+mapping_error)
                        external = f"entry:{oid}:{eid}"
                        records[external] = {"external_id": external, "record_type": "order_entry",
                            "order_id": oid, "entry_id": eid, "quantity": ea.get('quantity'),
                            "total_price": ea.get('totalPrice'), "base_price": ea.get('basePrice'),
                            "sku": (merchant.get('attributes') or {}).get('code'),
                            "external_product_id": product.get('id'),
                            "product_name": (merchant.get('attributes') or product.get('attributes') or {}).get('name'),
                            "mapping_error": mapping_error, "raw_attributes": ea,
                            "product_attributes": product.get('attributes') or {},
                            "merchant_product_attributes": merchant.get('attributes') or {},
                            "order_status": a.get('status'), "order_state": a.get('state'),
                            "order_creation_date": a.get('creationDate'),
                            "completed_date": a.get('completionDate'), "returned_date": a.get('returnedDate') or a.get('returnDate')}
                    entry_page += 1
                    count = (ep.get('meta') or {}).get('pageCount')
                    if not entries or (count is not None and entry_page >= int(count)) or (count is None and len(entries)<100):
                        break
                    if entry_page >= 10000:
                        raise AccessRequired('Kaspi: превышен лимит страниц позиций; sync не завершён')
            except AccessRequired as exc:
                errors.append('entries:'+oid+': '+str(exc))
        next_state = None
        next_offset = offset + len(selected)
        if period_mode and extras_selected:
            extra_offset = max(0, int(state.get("extra_offset") or 0)) + extras_requested
            extra_ids = state.get("extra_ids") or []
            next_state = ({"_qor_kaspi_cursor":1,"scope":period_scope,"start_ms":int(window_start.timestamp()*1000),
                "until_ms":int(until.timestamp()*1000),"page":page,"offset":len(data),
                "extra_ids":extra_ids,"extra_offset":extra_offset} if extra_offset < len(extra_ids) else None)
        elif period_mode and selected and next_offset < len(data):
            next_state = {"_qor_kaspi_cursor":1,"scope":"period","start_ms":int(window_start.timestamp()*1000),
                "until_ms":int(until.timestamp()*1000),"page":page,"offset":next_offset,
                "extra_ids":state.get("extra_ids") or [],"extra_offset":int(state.get("extra_offset") or 0)}
        elif selected and next_offset < len(data):
            next_state = {"_qor_kaspi_cursor":1,"direction":direction,"start_ms":int(window_start.timestamp()*1000),
                          "until_ms":int(until.timestamp()*1000),"page":page,"offset":next_offset}
        else:
            page_count = (payload.get('meta') or {}).get('pageCount')
            has_more_pages = bool(data) and ((page_count is not None and page + 1 < int(page_count))
                                               or (page_count is None and len(data) >= (10 if period_mode else 100)))
            if period_mode:
                extra_ids = state.get("extra_ids") or []
                extra_offset = max(0, int(state.get("extra_offset") or 0))
                if has_more_pages:
                    next_state = {"_qor_kaspi_cursor":1,"scope":period_scope,"start_ms":int(window_start.timestamp()*1000),
                        "until_ms":int(until.timestamp()*1000),"page":page+1,"offset":0,
                        "extra_ids":extra_ids,"extra_offset":extra_offset}
                elif not status_only and window_end < until:
                    # Kaspi accepts date-range filters but may reject wide windows.
                    # Split the selected range into one-week API windows without
                    # requesting anything outside the user's selected dates.
                    next_state = {"_qor_kaspi_cursor":1,"scope":"period",
                        "start_ms":int((window_end+timedelta(milliseconds=1)).timestamp()*1000),
                        "until_ms":int(until.timestamp()*1000),"page":0,"offset":0,
                        "extra_ids":extra_ids,"extra_offset":extra_offset}
                elif extra_offset < len(extra_ids):
                    next_state = {"_qor_kaspi_cursor":1,"scope":period_scope,
                        "start_ms":int(window_start.timestamp()*1000),"until_ms":int(until.timestamp()*1000),
                        "page":page,"offset":len(data),"extra_ids":extra_ids,"extra_offset":extra_offset}
                else:
                    next_state = None
            elif has_more_pages:
                next_state = {"_qor_kaspi_cursor":1,"direction":direction,"start_ms":int(window_start.timestamp()*1000),
                              "until_ms":int(until.timestamp()*1000),"page":page+1,"offset":0}
            elif direction == "backward" and window_start > history_start:
                previous_start = max(history_start, window_start - timedelta(days=7))
                next_state = {"_qor_kaspi_cursor":1,"direction":"backward",
                    "start_ms":int(previous_start.timestamp()*1000),
                    "until_ms":int(until.timestamp()*1000),"page":0,"offset":0}
            elif direction == "forward" and window_end < until:
                next_state = {"_qor_kaspi_cursor":1,"direction":"forward",
                    "start_ms":int((window_end+timedelta(milliseconds=1)).timestamp()*1000),
                    "until_ms":int(until.timestamp()*1000),"page":0,"offset":0}
        next_cursor = json.dumps(next_state,separators=(",",":")) if next_state else None
        return SyncResult('kaspi', list(records.values()),
            f'Kaspi: {len(records)} записей, {pages} страниц, обработано до 10 заказов.', next_cursor=next_cursor, warnings=errors)

    def update_order(self, order_id, status, code=None, cancellation_reason=None, cancellation_comment=None, number_of_space=None, security_code=None, send_code=False):
        state=self.connection_status()
        if state["missing"]: raise AccessRequired("Kaspi credentials отсутствуют: token")
        allowed={"ACCEPTED_BY_MERCHANT","COMPLETED","CANCELLED","ARRIVED","ASSEMBLE"}; status=str(status or "").strip().upper()
        if status not in allowed: raise AccessRequired("Недопустимый статус Kaspi")
        attrs={"status":status}
        if status in {"ACCEPTED_BY_MERCHANT","COMPLETED","CANCELLED","ARRIVED"} and not str(code or "").strip(): raise AccessRequired("Для этого статуса Kaspi требуется номер заказа code")
        if code: attrs["code"]=str(code).strip()
        if status=="CANCELLED":
            reasons={"BUYER_CANCELLATION_BY_MERCHANT","BUYER_NOT_REACHABLE","MERCHANT_OUT_OF_STOCK"}
            if cancellation_reason not in reasons: raise AccessRequired("Для отмены выберите допустимую причину")
            attrs["cancellationReason"]=cancellation_reason
            if cancellation_comment: attrs["cancellationComment"]=str(cancellation_comment)[:1000]
        if status=="ASSEMBLE":
            if not number_of_space or int(number_of_space)<1: raise AccessRequired("Для ASSEMBLE укажите количество мест/накладных")
            attrs["numberOfSpace"]=str(int(number_of_space))
        headers=self._headers()
        if status=="COMPLETED": headers.update({"X-Send-Code":"true","X-Security-Code":str(security_code or "")})
        _,result=_json_request(self.base_url,headers,method="POST",payload={"data":{"type":"orders","id":str(order_id),"attributes":attrs}})
        return result


    catalog_base = "https://kaspi.kz/shop/api/products/classification"
    import_base = "https://kaspi.kz/shop/api/products/import"

    def _get_json(self, url):
        return _json_request(url, self._headers())[1]

    def list_categories(self):
        """Return Kaspi seller catalog categories available for product import."""
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        headers = {**self._headers(), "Accept": "application/json"}
        return _json_request("https://kaspi.kz/shop/api/products/classification/categories", headers)[1]

    def list_category_attributes(self, category_code):
        """Get required/available product attributes for a Kaspi category."""
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        if not str(category_code or "").strip():
            raise AccessRequired("Укажите код категории Kaspi")
        url = self.catalog_base + "/attributes?" + urlencode({"c": str(category_code).strip()})
        headers = {**self._headers(), "Accept": "application/json"}
        return _json_request(url, headers)[1]

    def list_attribute_values(self, category_code, attribute_code):
        """Get allowed values for a category attribute."""
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        if not str(category_code or "").strip() or not str(attribute_code or "").strip():
            raise AccessRequired("Укажите код категории и характеристики Kaspi")
        url = self.catalog_base + "/attribute/values?" + urlencode({
            "c": str(category_code).strip(), "a": str(attribute_code).strip()
        })
        headers = {**self._headers(), "Accept": "application/json"}
        return _json_request(url, headers)[1]

    def import_products(self, products):
        """Submit seller product cards to Kaspi's documented asynchronous import API."""
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        if not isinstance(products, list) or not products or len(products) > 100:
            raise AccessRequired("Передайте от 1 до 100 карточек товара за один запрос")
        for index, product in enumerate(products):
            if not isinstance(product, dict):
                raise AccessRequired(f"Карточка {index + 1}: ожидается объект")
            for required in ("sku", "title", "brand", "category"):
                if not str(product.get(required) or "").strip():
                    raise AccessRequired(f"Карточка {index + 1}: заполните {required}")
            if len(str(product["sku"])) > 20:
                raise AccessRequired(f"Карточка {index + 1}: Kaspi допускает артикул до 20 символов")
        headers = {
            "Content-Type": "text/plain",
            "Accept": "application/json",
            "X-Auth-Token": str(self.credentials.get("token") or "").strip(),
        }
        _, result = _json_request(self.import_base, headers, method="POST", payload=products)
        return result

    def get_product_import_status(self, import_code):
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        code = str(import_code or "").strip()
        if not code or len(code) > 200:
            raise AccessRequired("Укажите код загрузки товара Kaspi")
        url = self.import_base + "?" + urlencode({"i": code})
        headers = {**self._headers(), "Accept": "application/json"}
        return _json_request(url, headers)[1]

    def get_product_import_result(self, import_code):
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        code = str(import_code or "").strip()
        if not code or len(code) > 200:
            raise AccessRequired("Укажите код загрузки товара Kaspi")
        url = self.import_base + "/result?" + urlencode({"i": code})
        headers = {**self._headers(), "Accept": "application/json"}
        return _json_request(url, headers)[1]

    def get_order(self, order_id, include_user=True):
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        params = {"include[orders]": "user"} if include_user else {}
        url = self.base_url + "/" + quote(str(order_id), safe="")
        if params:
            url += "?" + urlencode(params)
        return _json_request(url, self._headers())[1]

    def get_order_entries(self, order_id, page_size=100):
        if self.connection_status()["missing"]:
            raise AccessRequired("Kaspi credentials отсутствуют: token")
        size = min(100, max(1, int(page_size)))
        entries = []
        page = 0
        while True:
            url = self.base_url + "/" + quote(str(order_id), safe="") + "/entries?" + urlencode({
                "page[number]": page, "page[size]": size
            })
            payload = _json_request(url, self._headers())[1]
            batch = payload.get("data") or []
            entries.extend(batch)
            page += 1
            count = (payload.get("meta") or {}).get("pageCount")
            if not batch or (count is not None and page >= int(count)) or (count is None and len(batch) < size):
                return entries
            if page >= 10000:
                raise AccessRequired("Kaspi: превышен лимит страниц позиций; запрос не завершён")



class WildberriesConnector(Connector):
    provider = 'Wildberries'
    new_orders_url = 'https://marketplace-api.wildberries.ru/api/v3/orders/new'
    stats_base = 'https://statistics-api.wildberries.ru'
    # Current documented Finance API period method; the legacy statistics-api
    # reportDetailByPeriod endpoint is deprecated and no longer used.
    finance_url = 'https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed'
    stocks_url = 'https://seller-analytics-api.wildberries.ru/api/v2/stocks-report/products/products'
    statistics_page_size = 80000
    finance_page_size = 100000
    stocks_page_size = 250000
    seller_warehouses_url = 'https://marketplace-api.wildberries.ru/api/v3/warehouses'
    prices_filter_url = 'https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter'
    prices_upload_url = 'https://discounts-prices-api.wildberries.ru/api/v2/upload/task'

    def required_secret_names(self): return ['token']
    def test_connection(self):
        """Check actual Finance API access; a locally saved token alone proves nothing."""
        if self.connection_status()['missing']:
            raise AccessRequired('Wildberries credentials отсутствуют: token')
        from .wb_weekly import _request, finance_today
        day = finance_today() - timedelta(days=1)
        status, rows = _request(self.finance_url, self.credentials['token'], {
            'dateFrom': day.isoformat(), 'dateTo': day.isoformat(),
            'period': 'daily', 'limit': 1, 'rrdId': 0,
        })
        if status == 204:
            return {'message': 'Токен принят Finance API WB; финансовые права подтверждены, строк за вчера пока нет.', 'records_checked': 0}
        if isinstance(rows, list):
            return {'message': 'Токен принят Finance API WB; доступ к финансовым отчётам подтверждён.', 'records_checked': len(rows)}
        raise AccessRequired('WB Finance API вернул неожиданный ответ при проверке подключения.')

    def _headers(self): return {'Authorization':str(self.credentials.get('token') or '').strip(), 'Accept':'application/json', 'Content-Type':'application/json'}
    def test_connection(self):
        """Verify the saved token against Finance API without importing report rows."""
        if self.connection_status()['missing']:
            raise AccessRequired('Wildberries credentials отсутствуют: token')
        # Use the same account-token rate gate as report synchronization. A 204
        # is a valid authenticated response and simply means no rows were
        # published for yesterday yet.
        from .wb_weekly import _request, finance_today
        day = finance_today() - timedelta(days=1)
        status, rows = _request(self.finance_url, self.credentials['token'], {
            'dateFrom': day.isoformat(), 'dateTo': day.isoformat(),
            'period': 'daily', 'limit': 1, 'rrdId': 0,
        })
        if status == 204:
            return {'message': 'Токен принят Finance API WB; за вчера строки отчёта пока не опубликованы.', 'records_checked': 0}
        if isinstance(rows, list):
            return {'message': 'Токен принят Finance API WB; права на финансовые отчёты подтверждены.', 'records_checked': len(rows)}
        raise AccessRequired('WB Finance API вернул неожиданный ответ при проверке подключения.')
    def _request(self, url, method='GET', payload=None, interval=0):
        # Per-fetch endpoint pacing. Pagination respects documented WB intervals.
        previous = getattr(self, '_request_times', {}).get(url.split('?')[0])
        if previous is not None and interval:
            time.sleep(max(0, interval - (time.monotonic()-previous)))
        if not hasattr(self, '_request_times'): self._request_times = {}
        self._request_times[url.split('?')[0]] = time.monotonic()
        return _json_request(url, self._headers(), method=method, payload=payload)[1]

    def list_seller_warehouses(self):
        """List seller warehouses used for FBS inventory writes."""
        return self._request(self.seller_warehouses_url)

    def product_prices(self, nm_id):
        return self._request(self.prices_filter_url + "?" + urlencode({"filterNmID": int(nm_id), "limit": 100, "offset": 0}))

    def upload_prices(self, rows):
        if not isinstance(rows, list) or not rows or len(rows) > 1000:
            raise AccessRequired("WB: передайте от 1 до 1000 цен за запрос")
        return self._request(self.prices_upload_url, "POST", {"data": rows}, interval=10)

    def update_seller_stocks(self, warehouse_id, rows):
        if not str(warehouse_id).isdigit():
            raise AccessRequired("WB: укажите числовой ID склада продавца")
        if not isinstance(rows, list) or len(rows) > 1000:
            raise AccessRequired("WB: передайте не более 1000 остатков за запрос")
        if not rows:
            return {"ok": True, "updated": 0}
        url = "https://marketplace-api.wildberries.ru/api/v3/stocks/" + str(int(warehouse_id))
        return self._request(url, "PUT", {"stocks": rows}, interval=0.6)

    sections = ("new_orders", "order", "sale", "realization", "stocks", "products")

    def fetch_section_pages(self, section, cursor=None):
        """Yield bounded WB pages so staging can commit progress incrementally.

        Each yielded SyncResult contains only one API page. Cursor state is advanced
        only after a page has been successfully received, allowing safe resume.
        """
        if section not in self.sections:
            raise ValueError(f"Unknown WB section: {section}")
        if self.connection_status()['missing']:
            raise AccessRequired('Wildberries credentials отсутствуют: token')
        now = datetime.now(timezone.utc)
        start = (now-timedelta(days=90)).date().isoformat()
        try: state = json.loads(cursor) if cursor else {}
        except (ValueError, TypeError): state = {}
        if not isinstance(state, dict): state = {}
        state = dict(state)
        def emit(items, next_state, warnings=None):
            return SyncResult('wildberries', items, f'Wildberries {section}: {len(items)} записей.',
                              json.dumps(next_state, separators=(',', ':')), warnings or [])

        if section == 'new_orders':
            p = self._request(self.new_orders_url)
            out=[]
            for o in p.get('orders') or []:
                key=o.get('id') or o.get('rid')
                if key is None: continue
                external='new_order:'+str(key); out.append({**o,'external_id':external,'record_type':'new_order'})
            yield emit(out,state); return

        if section in ('order','sale'):
            path='/api/v1/supplier/orders' if section=='order' else '/api/v1/supplier/sales'
            date_from=start
            if state.get(section):
                try: date_from=max(start,(datetime.fromisoformat(state[section])-timedelta(days=2)).isoformat())
                except (ValueError,TypeError): pass
            previous=None
            for _ in range(10000):
                items=self._request(self.stats_base+path+'?'+urlencode({'dateFrom':date_from,'flag':0}),interval=60)
                if not isinstance(items,list): raise AccessRequired('WB: неожиданная схема '+section)
                if not items: return
                out=[]; ids=[]; latest=None
                for o in items:
                    key=(o.get('saleID') or o.get('saleId')) if section=='sale' else (o.get('srid') or o.get('odid'))
                    if not key: continue
                    external=section+':'+str(key); ids.append(external)
                    out.append({**o,'external_id':external,'record_type':section})
                    if o.get('lastChangeDate'): latest=max(latest or '',str(o['lastChangeDate']))
                if latest: state[section]=latest
                yield emit(out,state)
                if len(items)<self.statistics_page_size: return
                nxt=items[-1].get('lastChangeDate')
                if not nxt or (nxt==date_from and ids==previous): raise AccessRequired('WB: pagination cursor не продвинулся; выгрузка неполная')
                previous=ids; date_from=str(nxt)
            raise AccessRequired('WB: превышен лимит страниц; выгрузка неполная')

        if section == 'realization':
            rrd=int(state.get('realization_rrd') or 0)
            for _ in range(10000):
                items=self._request(self.finance_url,'POST',{'dateFrom':start,'dateTo':now.date().isoformat(),'period':'weekly','limit':self.finance_page_size,'rrdId':rrd},interval=60)
                if not items: return
                if not isinstance(items,list): raise AccessRequired('WB: неожиданная схема реализации')
                out=[]
                for o in items:
                    key=o.get('rrdId') or o.get('rrd_id')
                    if not key: continue
                    external='realization:'+str(key); out.append({**o,'external_id':external,'record_type':'realization'})
                nxt=items[-1].get('rrdId') or items[-1].get('rrd_id')
                if not nxt or int(nxt)<=rrd: raise AccessRequired('WB: rrdId не продвинулся')
                rrd=int(nxt); state['realization_rrd']=rrd
                yield emit(out,state)
            raise AccessRequired('WB: превышен лимит страниц реализации')

        if section == 'stocks':
            p=self._request(self.stocks_url,'POST',{'nmIDs':[],'currentPeriod':{'start':start,'end':now.date().isoformat()},'stockType':''},interval=20)
            data=p.get('data') or {}; items=data.get('items') or data.get('products') or (data if isinstance(data,list) else [])
            out=[]
            for o in items:
                nm=o.get('nmID') or o.get('nmId')
                if nm is None: continue
                qty=o.get('stockCount'); qty=qty if qty is not None else (o.get('stocks') or o.get('quantity') or o.get('stock') or 0)
                out.append({**o,'nmId':nm,'quantity':qty,'external_id':'stock:'+str(nm),'record_type':'stock'})
            yield emit(out,state); return

        if section == 'products':
            saved_cursor = state.get('products_cursor') or {}
            card_cursor = {'limit': 100}
            if isinstance(saved_cursor, dict):
                if saved_cursor.get('updatedAt'): card_cursor['updatedAt'] = saved_cursor['updatedAt']
                if saved_cursor.get('nmID'): card_cursor['nmID'] = saved_cursor['nmID']
            url='https://content-api.wildberries.ru/content/v2/get/cards/list'
            for _ in range(10000):
                p=self._request(url,'POST',{'settings':{'cursor':card_cursor,'filter':{'withPhoto':-1}}},interval=0.6)
                cards=p.get('cards') or []; out=[]
                for card in cards:
                    nm=card.get('nmID') or card.get('nmId')
                    if not nm: continue
                    for size in card.get('sizes') or [{}]:
                        chrt=size.get('chrtID') or size.get('chrtId') or 0; external=f'product:{nm}:{chrt}'
                        out.append({**card,'nmId':nm,'chrtId':chrt,'barcodes':size.get('skus') or [],'external_id':external,'record_type':'product'})
                yield emit(out,state)
                c=p.get('cursor') or {}
                if not cards or int(c.get('total',len(cards)))<100: return
                nxt={'limit':100,'updatedAt':c.get('updatedAt'),'nmID':c.get('nmID')}
                if not nxt['updatedAt'] or nxt==card_cursor: raise AccessRequired('WB: cursor карточек не продвинулся')
                card_cursor=nxt
                state['products_cursor'] = {'updatedAt': nxt['updatedAt'], 'nmID': nxt.get('nmID')}
            raise AccessRequired('WB: превышен лимит страниц карточек')

    def fetch(self, cursor=None, sections=None):
        """Compatibility wrapper over the single paged WB implementation.

        Production sync uses fetch_section_pages directly so pages can be committed
        incrementally. Tests/manual callers may still request an aggregate result here.
        Keeping this wrapper prevents a second, diverging WB algorithm.
        """
        selected = list(sections or self.sections)
        unknown = set(selected) - set(self.sections)
        if unknown:
            raise ValueError(f"Unknown WB sections: {sorted(unknown)}")
        try:
            state = json.loads(cursor) if cursor else {}
        except (ValueError, TypeError):
            state = {}
        if not isinstance(state, dict): state = {}
        records = {}
        warnings = []
        available = 0
        for section in selected:
            try:
                for piece in self.fetch_section_pages(section, json.dumps(state, separators=(',', ':'))):
                    available += 1
                    for row in piece.records:
                        key = row.get('external_id')
                        if key: records[key] = row
                    if piece.next_cursor:
                        state = json.loads(piece.next_cursor)
                    warnings.extend(piece.warnings or [])
            except AccessRequired as exc:
                warnings.append(f"{section}: {exc}")
        if not available and warnings:
            raise AccessRequired('WB: нет доступа ни к одному разделу. ' + '; '.join(warnings))
        return SyncResult('wildberries', list(records.values()), f'Wildberries: {len(records)} записей.',
                          json.dumps(state, separators=(',', ':')), warnings)


class OzonConnector(Connector):
    provider = "Ozon"
    fbs_url = "https://api-seller.ozon.ru/v4/posting/fbs/list"
    # Ozon autumn-2026 API: FBS v4 is cursor-paginated, while FBO v3
    # intentionally keeps offset pagination. Finance transaction v3 is retired;
    # accrual/by-day is the current historical financial feed.
    fbo_url = "https://api-seller.ozon.ru/v3/posting/fbo/list"
    accrual_url = "https://api-seller.ozon.ru/v1/finance/accrual/by-day"
    accrual_types_url = "https://api-seller.ozon.ru/v1/finance/accrual/types"
    product_list_url = "https://api-seller.ozon.ru/v3/product/list"
    product_info_url = "https://api-seller.ozon.ru/v3/product/info/list"
    product_attributes_url = "https://api-seller.ozon.ru/v4/product/info/attributes"
    product_stocks_url = "https://api-seller.ozon.ru/v4/product/info/stocks"
    product_prices_url = "https://api-seller.ozon.ru/v5/product/info/prices"

    def required_secret_names(self):
        return ["client_id", "api_key"]

    def _headers(self):
        return {
            "Client-Id": str(self.credentials.get("client_id") or "").strip(),
            "Api-Key": str(self.credentials.get("api_key") or "").strip(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _iso(value):
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")

    def test_connection(self):
        if self.connection_status()["missing"]:
            raise AccessRequired("Ozon credentials отсутствуют: client_id/api_key")
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=1)
        errors = []
        # Do not reject a valid FBO-only seller just because the FBS method is
        # unavailable for the account. One successful Ozon read is enough.
        checks = [
            (self.fbs_url, {"cursor":"", "sort_dir":"DESC", "filter":{"since":self._iso(since), "to":self._iso(now)}, "limit":1, "with":{"analytics_data":False, "financial_data":False}}),
            (self.fbo_url, {"dir":"DESC", "filter":{"since":self._iso(since), "to":self._iso(now)}, "limit":1, "offset":0}),
        ]
        for url, body in checks:
            try:
                _, payload = _json_request(url, self._headers(), timeout=12, method="POST", retries=1, payload=body)
                result = payload.get("result") or {}
                items = payload.get("postings") or (result.get("postings") if isinstance(result, dict) else result) or []
                return {"message":"Ozon: подключение подтверждено", "records_checked":len(items)}
            except AccessRequired as exc:
                errors.append(str(exc))
        raise AccessRequired("Ozon API не подтвердил доступ: " + " | ".join(errors))

    def fetch(self, cursor=None):
        if self.connection_status()["missing"]:
            raise AccessRequired("Ozon credentials отсутствуют: client_id/api_key")
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=90)
        records, errors = [], []
        counts = {"FBS":0, "FBO":0, "finance":0, "products":0, "stocks":0, "prices":0}

        # Catalogue is an independent source of truth. Postings and finance feeds do
        # not guarantee product names, photos, characteristics, prices or current stock.
        product_ids, offer_ids = [], []
        last_id = ""
        try:
            for _ in range(1000):
                _, payload = _json_request(self.product_list_url, self._headers(), method="POST",
                    payload={"filter":{"visibility":"ALL"}, "last_id":last_id, "limit":1000})
                result = payload.get("result") or {}
                items = result.get("items") or []
                for item in items:
                    if not isinstance(item, dict): continue
                    pid=item.get("product_id") or item.get("id"); offer=item.get("offer_id")
                    if pid is not None: product_ids.append(str(pid))
                    if offer: offer_ids.append(str(offer))
                    # Persist the catalogue row immediately. Rich-info/attributes are
                    # enrichment only and must never be able to turn a non-empty Ozon
                    # catalogue into "0 товаров" when one auxiliary endpoint fails.
                    records.append({"external_id":f"product:{pid or offer}","record_type":"product",**item})
                    counts["products"]+=1
                nxt=str(result.get("last_id") or "")
                if not items or not nxt or nxt==last_id: break
                last_id=nxt
            else: raise AccessRequired("Ozon products: превышен лимит страниц")

            # Rich product info in bounded batches: name/images/barcodes/status/commissions.
            for pos in range(0,len(product_ids),1000):
                batch=product_ids[pos:pos+1000]
                _, info = _json_request(self.product_info_url,self._headers(),method="POST",payload={"product_id":batch})
                for item in info.get("items") or (info.get("result") or {}).get("items") or []:
                    if not isinstance(item,dict): continue
                    pid=item.get("id") or item.get("product_id")
                    offer=item.get("offer_id")
                    records.append({"external_id":f"product-info:{pid or offer}","record_type":"product",**item})

            # Attributes can contain the human title/characteristics even when info/list is sparse.
            attr_cursor=""
            for _ in range(1000):
                body={"filter":{"visibility":"ALL"},"limit":1000}
                if attr_cursor: body["last_id"]=attr_cursor
                _, attrs = _json_request(self.product_attributes_url,self._headers(),method="POST",payload=body)
                result=attrs.get("result") or attrs
                items=result.get("items") or [] if isinstance(result,dict) else []
                for item in items:
                    if not isinstance(item,dict): continue
                    pid=item.get("id") or item.get("product_id"); offer=item.get("offer_id")
                    records.append({"external_id":f"attributes:{pid or offer}","record_type":"product",**item})
                nxt=str(result.get("last_id") or "") if isinstance(result,dict) else ""
                if not items or not nxt or nxt==attr_cursor: break
                attr_cursor=nxt
        except AccessRequired as exc:
            errors.append("PRODUCTS: "+str(exc))

        # Current FBS/rFBS stock snapshots. Keep them non-financial.
        try:
            stock_cursor=""
            for _ in range(1000):
                body={"filter":{"visibility":"ALL"},"limit":1000,"cursor":stock_cursor}
                _, payload=_json_request(self.product_stocks_url,self._headers(),method="POST",payload=body)
                items=payload.get("items") or (payload.get("result") or {}).get("items") or []
                for item in items:
                    if not isinstance(item,dict): continue
                    pid=item.get("product_id"); offer=item.get("offer_id")
                    records.append({"external_id":f"stock:{pid or offer}","record_type":"stock",**item})
                    counts["stocks"]+=1
                nxt=str(payload.get("cursor") or (payload.get("result") or {}).get("cursor") or "")
                if not items or not nxt or nxt==stock_cursor: break
                stock_cursor=nxt
        except AccessRequired as exc:
            errors.append("STOCKS: "+str(exc))

        # Price feed is separate from catalogue and may change without card changes.
        try:
            price_cursor=""
            for _ in range(1000):
                body={"filter":{"visibility":"ALL"},"limit":1000,"cursor":price_cursor}
                _, payload=_json_request(self.product_prices_url,self._headers(),method="POST",payload=body)
                items=payload.get("items") or (payload.get("result") or {}).get("items") or []
                for item in items:
                    if not isinstance(item,dict): continue
                    pid=item.get("product_id"); offer=item.get("offer_id")
                    records.append({"external_id":f"price:{pid or offer}","record_type":"product",**item})
                    counts["prices"]+=1
                nxt=str(payload.get("cursor") or (payload.get("result") or {}).get("cursor") or "")
                if not items or not nxt or nxt==price_cursor: break
                price_cursor=nxt
        except AccessRequired as exc:
            errors.append("PRICES: "+str(exc))

        # FBS v4: postings/cursor/has_next are top-level fields.
        fbs_cursor = ""
        try:
            for _ in range(500):
                body = {"sort_dir":"DESC", "cursor":fbs_cursor,
                        "filter":{"since":self._iso(since), "to":self._iso(now)}, "limit":100,
                        "with":{"analytics_data":True, "financial_data":True}}
                _, payload = _json_request(self.fbs_url, self._headers(), method="POST", payload=body)
                items = payload.get("postings") or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    pn = str(item.get("posting_number") or "")
                    if not pn:
                        continue
                    records.append({"external_id":f"posting:FBS:{pn}", "record_type":"posting", "scheme":"FBS", **item})
                    counts["FBS"] += 1
                if not payload.get("has_next"):
                    break
                nxt = str(payload.get("cursor") or "")
                if not nxt or nxt == fbs_cursor:
                    raise AccessRequired("Ozon FBS: курсор не продвинулся; выгрузка неполная")
                fbs_cursor = nxt
            else:
                raise AccessRequired("Ozon FBS: превышен лимит страниц; выгрузка неполная")
        except AccessRequired as exc:
            errors.append("FBS: " + str(exc))

        # FBO v3: unlike FBS v4, this endpoint still uses offset pagination.
        offset = 0
        try:
            for _ in range(500):
                body = {"dir":"DESC", "filter":{"since":self._iso(since), "to":self._iso(now)}, "limit":100, "offset":offset}
                _, payload = _json_request(self.fbo_url, self._headers(), method="POST", payload=body)
                result = payload.get("result") or {}
                items = result.get("postings") if isinstance(result, dict) else result
                items = items or payload.get("postings") or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    pn = str(item.get("posting_number") or "")
                    if not pn:
                        continue
                    records.append({"external_id":f"posting:FBO:{pn}", "record_type":"posting", "scheme":"FBO", **item})
                    counts["FBO"] += 1
                if len(items) < 100:
                    break
                offset += len(items)
            else:
                raise AccessRequired("Ozon FBO: превышен лимит страниц; выгрузка неполная")
        except AccessRequired as exc:
            errors.append("FBO: " + str(exc))

        # Finance: read every day and every last_id page. Null/incomplete nested
        # objects are retained safely instead of crashing the entire sync.
        accrual_types = {}
        try:
            _, type_payload = _json_request(self.accrual_types_url,self._headers(),method="POST",payload={})
            type_items=type_payload.get("types") or (type_payload.get("result") or {}).get("types") or type_payload.get("items") or []
            for t in type_items:
                if isinstance(t,dict) and t.get("id") is not None:
                    accrual_types[str(t.get("id"))]=str(t.get("name") or t.get("title") or t.get("type") or t.get("id"))
        except AccessRequired as exc:
            errors.append("FINANCE_TYPES: "+str(exc))

        accrual_day = since.date()
        try:
            while accrual_day <= now.date():
                last_id = ""
                for _ in range(1000):
                    _, payload = _json_request(self.accrual_url, self._headers(), method="POST",
                        payload={"date":accrual_day.isoformat(), "last_id":last_id})
                    items = payload.get("accruals") or []
                    for index, item in enumerate(items):
                        if not isinstance(item, dict):
                            errors.append(f"FINANCE {accrual_day}: пропущена некорректная запись #{index}")
                            continue
                        posting = item.get("posting") or {}
                        if not isinstance(posting, dict):
                            posting = {}
                        # `type_id` is the accrual classification. Never use it as a
                        # record identity: many accruals share the same type and would
                        # overwrite each other in staging. Ozon's current by-day schema
                        # does not guarantee a unique accrual id, so derive a stable
                        # content identity when no explicit id is present.
                        identity = item.get("id")
                        if identity is None:
                            identity = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:32]
                        total=item.get("total_amount") or {}
                        if not isinstance(total,dict): total={}
                        type_id=item.get("type_id")
                        records.append({**item, "external_id":"accrual:"+str(identity), "record_type":"finance_accrual",
                            "amount":total.get("amount"), "currency":total.get("currency"),
                            "operation_type":str(type_id or ""), "operation_type_name":accrual_types.get(str(type_id), ""), "_accrual_type_names":accrual_types})
                        counts["finance"] += 1
                    nxt = str(payload.get("last_id") or "")
                    if not items or not nxt or nxt == last_id:
                        break
                    last_id = nxt
                else:
                    raise AccessRequired("Ozon: превышен лимит страниц начислений; выгрузка неполная")
                accrual_day += timedelta(days=1)
        except AccessRequired as exc:
            errors.append("FINANCE: " + str(exc))

        if not records:
            if errors:
                raise AccessRequired("Ozon API не вернул данные: " + " | ".join(errors))
            return SyncResult("ozon", [], "Ozon: за последние 90 дней API вернул 0 записей.")
        msg = f"Ozon: products={counts['products']}, stocks={counts['stocks']}, prices={counts['prices']}, FBS={counts['FBS']}, FBO={counts['FBO']}, finance={counts['finance']}. Всего {len(records)}."
        if errors:
            msg += " Частично недоступно: " + "; ".join(errors)
        return SyncResult("ozon", records, msg, warnings=errors)


class DemoAdapter(Connector):
    provider = "DEMO"
    def connection_status(self): return {"provider": self.account.channel, "mode": "demo", "configured": True, "missing": [], "live": False}
    def fetch(self, cursor=None): return SyncResult("demo", [{"external_id": "DEMO-001", "sku": "DEMO-SKU", "quantity": 1}], "DEMO connector: записи не проведены в финансовый учёт.")


class CSVAdapter(Connector):
    provider = "CSV/XLSX"
    def connection_status(self): return {"provider": self.account.channel, "mode": "csv", "configured": True, "missing": [], "live": False}
    def fetch(self, cursor=None): return SyncResult("csv", [], "Загрузите отчёт в разделе Импорт / Экспорт и подтвердите предварительный просмотр.")


def connector(account, credentials=None):
    if account.mode == "demo": return DemoAdapter(account, credentials)
    if account.mode == "csv": return CSVAdapter(account, credentials)
    return {"Kaspi": KaspiConnector, "Wildberries": WildberriesConnector, "Ozon": OzonConnector}.get(account.channel, CSVAdapter)(account, credentials)
