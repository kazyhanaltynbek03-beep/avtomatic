from datetime import date
from typing import Literal
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CompanyIn(Strict):
    name: str = Field(min_length=1, max_length=160)
    bin: str = Field(pattern=r"^\d{12}$")
    kind: Literal["ИП", "ТОО"] = "ИП"
    active: bool = True


class ProductIn(Strict):
    version: int | None = Field(default=None, ge=1)
    catalog_kind: Literal["master", "marketplace"] | None = None
    description: str = Field(default="", max_length=10000)
    barcode: str = Field(default="", max_length=100)
    purchase_cost: int = Field(default=0, ge=0, le=10**14)
    custom_fields: dict = Field(default_factory=dict)
    marketplace_stock_allocations: dict | None = None
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    category: str = ""
    article: str = ""
    brand: str = ""
    supplier: str = ""
    country: str = ""
    media: list[str] = []
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    fx_rate: int = Field(default=10000, gt=0)  # scaled by 10,000
    weight_g: int = Field(default=0, ge=0)
    volume_cm3: int = Field(default=0, ge=0)
    min_price: int = Field(default=0, ge=0, le=10**14)
    recommended_price: int = Field(default=0, ge=0, le=10**14)
    price: int = Field(default=0, ge=0, le=10**14)
    min_stock: int = Field(default=5, ge=0)
    active: bool = True
    specifications: dict = {}


class AccountIn(Strict):
    company_id: int
    name: str = Field(min_length=1, max_length=120)
    channel: Literal["Kaspi", "Wildberries", "Ozon", "Offline", "B2B"]
    mode: Literal["csv", "demo", "api"] = "api"


class CustomerIn(Strict):
    company_id: int
    name: str = Field(min_length=1, max_length=160)
    phone: str = ""
    bin: str = ""


class PurchaseLine(Strict):
    product_id: int
    quantity: int = Field(gt=0, le=1000000)
    unit_cost: int = Field(ge=0, le=10**12)
    # Cost is in the line currency's minor units; 10_000 means FX 1.0000.
    currency: str = Field(default="KZT", min_length=3, max_length=3)
    fx_rate: int = Field(default=10000, gt=0, le=10**10)


class PurchaseIn(Strict):
    company_id: int
    reference: str = Field(min_length=1, max_length=100)
    supplier: str = Field(min_length=1, max_length=160)
    date: date
    extra_cost: int = Field(default=0, ge=0, le=10**14)
    cost_breakdown: dict[str, int] = {}
    allocation_method: Literal["quantity", "weight", "volume", "value"] = "value"
    paid: int = Field(default=0, ge=0, le=10**14)
    lines: list[PurchaseLine] = Field(min_length=1, max_length=500)


class SaleIn(Strict):
    source_fx: dict = {}
    company_id: int
    account_id: int
    customer_id: int | None = None
    product_id: int
    reference: str = Field(min_length=1, max_length=120)
    date: date
    due_date: date | None = None
    quantity: int = Field(gt=0, le=1000000)
    unit_price: int = Field(ge=0, le=10**12)
    discount: int = Field(default=0, ge=0, le=10**14)
    commission: int = Field(default=0, ge=0, le=10**14)
    logistics: int = Field(default=0, ge=0, le=10**14)
    advertising: int = Field(default=0, ge=0, le=10**14)
    paid: int = Field(default=0, ge=0, le=10**14)


class ReturnIn(Strict):
    sale_id: int
    reference: str = Field(min_length=1, max_length=120)
    date: date
    quantity: int = Field(gt=0)
    refund: int = Field(default=0, ge=0)


class ReturnStatusIn(Strict):
    status: Literal["approved", "in_transit", "received", "inspection", "restocked", "defective", "written_off"]
    reason: str = Field(default="", max_length=160)


class ExpenseIn(Strict):
    source_fx: dict = {}
    company_id: int
    account_id: int | None = None
    reference: str = Field(min_length=1, max_length=120)
    date: date
    category: str = Field(min_length=1, max_length=80)
    project: str = Field(default="", max_length=120)
    payment_method: str = Field(default="", max_length=60)
    description: str = ""
    amount: int = Field(ge=-(10**14), le=10**14, ne=0)
    paid: bool = False


class CashIn(Strict):
    company_id: int
    sale_id: int | None = None
    purchase_id: int | None = None
    expense_id: int | None = None
    reference: str = Field(min_length=1, max_length=120)
    date: date
    amount: int = Field(ge=-(10**14), le=10**14)
    category: str = Field(min_length=1, max_length=60)
    description: str = ""


class AdjustIn(Strict):
    company_id: int
    product_id: int
    date: date
    quantity: int
    unit_cost: int = Field(default=0, ge=0)
    kind: Literal["receipt", "writeoff", "defect", "adjustment"] = "adjustment"
    reason: str = Field(min_length=5, max_length=160)
    reference: str | None = Field(default=None, min_length=8, max_length=120)


class StockCountIn(Strict):
    company_id: int
    product_id: int
    counted_quantity: int = Field(ge=0, le=10**9)
    unit_cost: int | None = Field(default=None, ge=0, le=10**14)
    reason: str = Field(min_length=5, max_length=160)
    idempotency_key: str = Field(min_length=16, max_length=100)


class UserIn(Strict):
    email: str = Field(pattern=r"^\S+@\S+\.\S+$", max_length=200)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(default="", max_length=128)
    role: Literal["Owner", "Admin", "Accountant", "Manager", "Warehouse", "Marketing"]
    company_ids: list[int] = []
    active: bool = True


class NicheIn(Strict):
    name: str = Field(min_length=1, max_length=150)
    source: str = Field(min_length=5, max_length=2000)
    observed_at: date
    data: dict

class CounterpartyIn(Strict):
    company_id: int
    name: str = Field(min_length=1, max_length=180)
    bin: str = Field(default="", pattern=r"^$|^\d{12}$")
    kind: Literal["supplier", "buyer", "other"] = "supplier"
    notes: str = ""
    active: bool = True

class BankTransactionIn(Strict):
    company_id: int
    reference: str = Field(min_length=1, max_length=140)
    date: date
    account: str = Field(min_length=1, max_length=120)
    counterparty: str = Field(default="", max_length=180)
    purpose: str = ""
    direction: Literal["in", "out"]
    amount: int = Field(gt=0, le=10**14)
    category: str = Field(default="uncategorized", max_length=80)
    reconciled: bool = False

class TaxRuleIn(Strict):
    company_id: int
    name: str = Field(min_length=1, max_length=160)
    rate_bps: int = Field(ge=0, le=10000)
    valid_from: date
    valid_to: date | None = None
    basis: str = Field(default="manual_review", max_length=80)
    active: bool = True
    accountant_approved: bool = False

class GeneratedDocumentIn(Strict):
    company_id: int
    number: str = Field(min_length=1, max_length=80)
    kind: Literal["contract", "invoice", "waybill", "act", "commercial_offer", "payment_invoice"]
    date: date
    counterparty: str = Field(default="", max_length=180)
    amount: int = Field(default=0, ge=0, le=10**14)
    status: Literal["draft", "approved", "cancelled"] = "draft"
    payload: dict = {}


class OpeningInventoryIn(Strict):
    company_id: int
    product_id: int
    reference: str = Field(min_length=1,max_length=120)
    date: date
    quantity: int = Field(gt=0,le=1000000)
    unit_cost: int = Field(gt=0,le=10**12)
    currency: str = Field(default='KZT',pattern='^[A-Z]{3}$')
    fx_rate: int = Field(default=10000,gt=0,le=10**10)
    evidence: str = Field(min_length=3,max_length=250)


class WBProductCostIn(Strict):
    account_id: int = Field(gt=0)
    external_key: str = Field(min_length=1, max_length=200)
    nm_id: str = Field(default="", max_length=40)
    seller_article: str = Field(default="", max_length=120)
    barcode: str = Field(default="", max_length=80)
    product_name: str = Field(default="", max_length=200)
    unit_cost: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: Literal["KZT"] = "KZT"
    effective_from: date


class WBProductCostBulkIn(Strict):
    account_id: int = Field(gt=0)
    external_keys: list[str] = Field(min_length=1, max_length=1000)
    unit_cost: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    effective_from: date
