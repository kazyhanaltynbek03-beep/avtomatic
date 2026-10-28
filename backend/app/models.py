from datetime import datetime, timezone, date as DateType
from sqlalchemy import (
    String,
    Integer,
    BigInteger,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    JSON,
    Text,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now():
    return datetime.now(timezone.utc)


def business_today():
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Almaty")).date()


class Record:
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Company(Record, Base):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String(160))
    bin: Mapped[str] = mapped_column(String(12), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="ИП")
    active: Mapped[bool] = mapped_column(default=True)


class User(Record, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))
    company_ids: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(default=True)


class Session(Record, Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Record, Base):
    __tablename__ = "login_attempts"
    identity: Mapped[str] = mapped_column(String(64), index=True)


class Product(Record, Base):
    __tablename__ = "products"
    sku: Mapped[str] = mapped_column(String(100), unique=True)
    # Master SKUs are created by the business. Marketplace rows are legacy/imported
    # catalogue records retained for reporting and remapping; they remain separate.
    catalog_kind: Mapped[str] = mapped_column(String(20), default="master", server_default="master", nullable=False)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), default="")
    article: Mapped[str] = mapped_column(String(120), default="")
    brand: Mapped[str] = mapped_column(String(120), default="")
    supplier: Mapped[str] = mapped_column(String(160), default="")
    country: Mapped[str] = mapped_column(String(100), default="")
    media: Mapped[list] = mapped_column(JSON, default=list)
    currency: Mapped[str] = mapped_column(String(3), default="KZT")
    fx_rate: Mapped[int] = mapped_column(BigInteger, default=10000)  # 1.0000 = 10000
    weight_g: Mapped[int] = mapped_column(Integer, default=0)
    volume_cm3: Mapped[int] = mapped_column(Integer, default=0)
    min_price: Mapped[int] = mapped_column(BigInteger, default=0)
    recommended_price: Mapped[int] = mapped_column(BigInteger, default=0)
    price: Mapped[int] = mapped_column(BigInteger, default=0)
    min_stock: Mapped[int] = mapped_column(default=5)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    active: Mapped[bool] = mapped_column(default=True)
    specifications: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (CheckConstraint("price >= 0 AND min_price >= 0 AND recommended_price >= 0 AND min_stock >= 0 AND weight_g >= 0 AND volume_cm3 >= 0 AND fx_rate > 0"),)


class Account(Record, Base):
    __tablename__ = "accounts"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(default=True)
    mode: Mapped[str] = mapped_column(String(20), default="api")
    credential_ref: Mapped[str] = mapped_column(String(100), default="")
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str] = mapped_column(String(20), default="never")
    sync_error: Mapped[str] = mapped_column(String(500), default="")
    sync_cursor: Mapped[str] = mapped_column(Text, default="")
    settlement_currency: Mapped[str] = mapped_column(String(3), default="KZT")
    settlement_fx_rate: Mapped[int] = mapped_column(BigInteger, default=10000)
    integration_settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class IntegrationSecret(Record, Base):
    __tablename__ = "integration_secrets"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True, index=True)
    encrypted_payload: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(12), default="")


class ExchangeRate(Record, Base):
    __tablename__ = "exchange_rates"
    currency: Mapped[str] = mapped_column(String(3), index=True)
    rate_date: Mapped[DateType] = mapped_column(Date, index=True)
    rate_scaled: Mapped[int] = mapped_column(BigInteger)  # KZT per unit * 10,000
    source: Mapped[str] = mapped_column(String(30), default="NBK")
    __table_args__ = (
        UniqueConstraint("currency", "rate_date", name="uq_exchange_rate_currency_date"),
        CheckConstraint("rate_scaled > 0"),
    )


class MarketplaceRecord(Record, Base):
    stage_status: Mapped[str] = mapped_column(String(30),default="received")
    reason_code: Mapped[str] = mapped_column(String(100),default="")
    """Idempotent staging ledger for records received from marketplace APIs.

    Raw marketplace orders are not silently booked as financial sales: booking requires
    enough product/cost/payment data. This table preserves every external record once.
    """
    __tablename__ = "marketplace_records"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    source: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="received")
    __table_args__ = (UniqueConstraint("account_id", "source", "external_id", name="uq_marketplace_record_external"),)


class MarketplaceProductMapping(Record, Base):
    __tablename__ = "marketplace_product_mappings"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    external_key: Mapped[str] = mapped_column(String(200))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    __table_args__ = (UniqueConstraint("account_id", "external_key", name="uq_marketplace_mapping"),)


class MarketplaceProductCost(Record, Base):
    """Seller-scoped, dated cost basis for a stable marketplace product key.

    Values are stored in KZT tiyn. A new effective date creates a history row;
    changing an existing date is audited by the API before it is updated.
    """
    __tablename__ = "marketplace_product_costs"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    external_key: Mapped[str] = mapped_column(String(200))
    nm_id: Mapped[str] = mapped_column(String(40), default="")
    seller_article: Mapped[str] = mapped_column(String(120), default="")
    barcode: Mapped[str] = mapped_column(String(80), default="")
    product_name: Mapped[str] = mapped_column(String(200), default="")
    unit_cost: Mapped[int] = mapped_column(BigInteger)  # KZT tiyn
    currency: Mapped[str] = mapped_column(String(3), default="KZT")
    effective_from: Mapped[DateType] = mapped_column(Date, index=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    __table_args__ = (
        UniqueConstraint("account_id", "external_key", "effective_from", name="uq_wb_cost_effective"),
        CheckConstraint("unit_cost > 0"),
    )


class CanonicalEvent(Record, Base):
    __tablename__ = "canonical_events"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    identity: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    target_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="posted")


class Customer(Record, Base):
    __tablename__ = "customers"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(40), default="")
    bin: Mapped[str] = mapped_column(String(12), default="")


class Purchase(Record, Base):
    __tablename__ = "purchases"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    reference: Mapped[str] = mapped_column(String(100), unique=True)
    supplier: Mapped[str] = mapped_column(String(160))
    date: Mapped[DateType] = mapped_column(Date)
    total: Mapped[int] = mapped_column(BigInteger)
    extra_cost: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    allocation_method: Mapped[str] = mapped_column(String(20), default="value")


class Batch(Record, Base):
    __tablename__ = "batches"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("purchases.id"))
    date: Mapped[DateType] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer)
    remaining: Mapped[int] = mapped_column(Integer)
    total_cost: Mapped[int] = mapped_column(BigInteger)
    remaining_cost: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        CheckConstraint(
            "quantity > 0 AND remaining >= 0 AND remaining <= quantity AND total_cost >= 0 AND remaining_cost >= 0"
        ),
    )


class Sale(Record, Base):
    source_fx: Mapped[dict] = mapped_column(JSON, default=dict)
    __tablename__ = "sales"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    reference: Mapped[str] = mapped_column(String(120), unique=True)
    date: Mapped[DateType] = mapped_column(Date)
    due_date: Mapped[DateType | None] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer)
    revenue: Mapped[int] = mapped_column(BigInteger)
    # Discount is stored separately for traceability; revenue is always the net
    # recognised amount used by the deterministic financial engine.
    discount: Mapped[int] = mapped_column(BigInteger, default=0)
    cogs: Mapped[int] = mapped_column(BigInteger)
    # True when revenue/quantity are confirmed but FIFO cost is not available yet.
    cogs_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    commission: Mapped[int] = mapped_column(BigInteger, default=0)
    logistics: Mapped[int] = mapped_column(BigInteger, default=0)
    advertising: Mapped[int] = mapped_column(BigInteger, default=0)
    __table_args__ = (
        CheckConstraint(
            "quantity > 0 AND revenue >= 0 AND cogs >= 0 AND commission >= 0 AND logistics >= 0 AND advertising >= 0"
        ),
    )


class Allocation(Record, Base):
    __tablename__ = "allocations"
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    cost: Mapped[int] = mapped_column(BigInteger)
    returned: Mapped[int] = mapped_column(default=0)
    returned_cost: Mapped[int] = mapped_column(BigInteger, default=0)


class Return(Record, Base):
    __tablename__ = "returns"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"))
    date: Mapped[DateType] = mapped_column(Date)
    reference: Mapped[str] = mapped_column(String(120), unique=True)
    quantity: Mapped[int] = mapped_column(Integer)
    revenue: Mapped[int] = mapped_column(BigInteger)
    cogs: Mapped[int] = mapped_column(BigInteger)
    # Existing returns were already restocked by the previous posting logic.
    # New returns start pending and become available only after inspection.
    inventory_status: Mapped[str] = mapped_column(String(30), default="requested", server_default="requested")


class ReturnInventoryAllocation(Record, Base):
    __tablename__ = "return_inventory_allocations"
    return_id: Mapped[int] = mapped_column(ForeignKey("returns.id"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    cost: Mapped[int] = mapped_column(BigInteger)
    restocked: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        CheckConstraint("quantity > 0 AND cost >= 0"),
        UniqueConstraint("return_id", "batch_id", name="uq_return_inventory_return_batch"),
    )


class MarketplaceReturn(Record, Base):
    """Isolated marketplace return observations; never participates in ERP P&L."""
    __tablename__ = "marketplace_returns"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    marketplace: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(40))
    external_return_id: Mapped[str] = mapped_column(String(200))
    external_order_id: Mapped[str] = mapped_column(String(160), default="")
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    product_name: Mapped[str] = mapped_column(String(240), default="")
    sku: Mapped[str] = mapped_column(String(120), default="")
    image_url: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_date: Mapped[DateType | None] = mapped_column(Date, nullable=True)
    issue_date: Mapped[DateType | None] = mapped_column(Date, nullable=True)
    request_date: Mapped[DateType | None] = mapped_column(Date, nullable=True)
    financial_return_date: Mapped[DateType | None] = mapped_column(Date, nullable=True)
    detected_date: Mapped[DateType] = mapped_column(Date)
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # KZT tiyn; NULL until source confirms it.
    currency: Mapped[str] = mapped_column(String(3), default="KZT")
    return_status: Mapped[str] = mapped_column(String(40), default="detected")
    financial_status: Mapped[str] = mapped_column(String(30), default="unconfirmed")
    accounted_status: Mapped[str] = mapped_column(String(20), default="unverified")
    reason: Mapped[str] = mapped_column(Text, default="")
    guarantee_case: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    defect: Mapped[str] = mapped_column(Text, default="")
    examination: Mapped[str] = mapped_column(Text, default="")
    seller_decision: Mapped[str] = mapped_column(Text, default="")
    marketplace_decision: Mapped[str] = mapped_column(Text, default="")
    item_condition: Mapped[str] = mapped_column(String(30), default="unknown")
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("account_id", "source", "external_return_id", name="uq_marketplace_return_identity"),
        CheckConstraint("quantity IS NULL OR quantity > 0"),
        CheckConstraint("amount IS NULL OR amount >= 0"),
        CheckConstraint("accounted_status IN ('yes','no','unverified')"),
    )


class MarketplaceReturnAudit(Record, Base):
    __tablename__ = "marketplace_return_audits"
    return_id: Mapped[int] = mapped_column(ForeignKey("marketplace_returns.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class MarketplaceReturnSyncState(Record, Base):
    __tablename__ = "marketplace_return_sync_states"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="never")
    cursor: Mapped[str] = mapped_column(String(200), default="")
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Movement(Record, Base):
    __tablename__ = "movements"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"))
    date: Mapped[DateType] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer)
    cost: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(30))
    reference: Mapped[str] = mapped_column(String(160))


class Expense(Record, Base):
    source_fx: Mapped[dict] = mapped_column(JSON, default=dict)
    __tablename__ = "expenses"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    reference: Mapped[str] = mapped_column(String(120), unique=True)
    date: Mapped[DateType] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(80))
    project: Mapped[str] = mapped_column(String(120), default="")
    payment_method: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (CheckConstraint("amount != 0", name="ck_expenses_amount_nonzero"),)


class CashEntry(Record, Base):
    __tablename__ = "cash"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id"))
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("purchases.id"))
    expense_id: Mapped[int | None] = mapped_column(ForeignKey("expenses.id"))
    reference: Mapped[str] = mapped_column(String(140), unique=True)
    date: Mapped[DateType] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text, default="")


class Document(Record, Base):
    __tablename__ = "documents"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40), default="document")
    path: Mapped[str] = mapped_column(String(250))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)


class Audit(Record, Base):
    __tablename__ = "audit"
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Record, Base):
    __tablename__ = "jobs"
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIThread(Record, Base):
    __tablename__ = "ai_threads"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    agent: Mapped[str] = mapped_column(String(30), default="rick")
    title: Mapped[str] = mapped_column(String(180), default="Новый чат")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class AIMessage(Record, Base):
    __tablename__ = "ai_messages"
    thread_id: Mapped[int] = mapped_column(ForeignKey("ai_threads.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class ProductCardVersion(Record, Base):
    __tablename__ = "product_card_versions"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    marketplace: Mapped[str] = mapped_column(String(20), default="kaspi")
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(240), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    characteristics: Mapped[dict] = mapped_column(JSON, default=dict)
    image_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parent_version_id: Mapped[int | None] = mapped_column(ForeignKey("product_card_versions.id"), nullable=True)
    optimization_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    review_state: Mapped[str] = mapped_column(String(30), default="idle")
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportRun(Record, Base):
    __tablename__ = "imports"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    fingerprint: Mapped[str] = mapped_column(String(64))
    mapping: Mapped[dict] = mapped_column(JSON)
    rows: Mapped[list] = mapped_column(JSON)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="preview")


class Niche(Record, Base):
    __tablename__ = "niches"
    name: Mapped[str] = mapped_column(String(150))
    source: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[DateType] = mapped_column(Date)
    data: Mapped[dict] = mapped_column(JSON)
    method: Mapped[str] = mapped_column(
        Text, default="Взвешенный индекс v1; данные пользователя"
    )


class Setting(Base):
    __tablename__ = "settings"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    business_name: Mapped[str] = mapped_column(String(160), default="QOR Business")
    currency: Mapped[str] = mapped_column(String(3), default="KZT")
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Almaty")


# Composite access-pattern indexes for company scoping and period reports.
from sqlalchemy import Index

for _model in (Purchase, Batch, Sale, Return, Movement, Expense, CashEntry):
    Index(
        "ix_" + _model.__tablename__ + "_company_date", _model.company_id, _model.date
    )
Index("ix_sales_account_date", Sale.account_id, Sale.date)
Index("ix_allocations_sale", Allocation.sale_id)
Index("ix_cash_sale", CashEntry.sale_id)
Index("ix_returns_sale", Return.sale_id)
Index("ix_batches_fifo", Batch.company_id, Batch.product_id, Batch.date)
Index("ix_jobs_queue", Job.status, Job.id)
Index("ix_imports_fingerprint_status", ImportRun.fingerprint, ImportRun.status)
Index("ix_audit_created", Audit.created_at)

class Counterparty(Record, Base):
    __tablename__ = "counterparties"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    bin: Mapped[str] = mapped_column(String(12), default="")
    kind: Mapped[str] = mapped_column(String(30), default="supplier")
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(default=True)

class BankTransaction(Record, Base):
    __tablename__ = "bank_transactions"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    reference: Mapped[str] = mapped_column(String(140), unique=True)
    date: Mapped[DateType] = mapped_column(Date, index=True)
    account: Mapped[str] = mapped_column(String(120))
    counterparty: Mapped[str] = mapped_column(String(180), default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    direction: Mapped[str] = mapped_column(String(10))
    amount: Mapped[int] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(80), default="uncategorized")
    reconciled: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (CheckConstraint("amount > 0"), CheckConstraint("direction IN ('in','out')"))

class TaxRule(Record, Base):
    __tablename__ = "tax_rules"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    rate_bps: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[DateType] = mapped_column(Date)
    valid_to: Mapped[DateType | None] = mapped_column(Date, nullable=True)
    basis: Mapped[str] = mapped_column(String(80), default="manual_review")
    active: Mapped[bool] = mapped_column(default=True)
    accountant_approved: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (CheckConstraint("rate_bps >= 0 AND rate_bps <= 10000"),)

class GeneratedDocument(Record, Base):
    __tablename__ = "generated_documents"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    number: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(40))
    date: Mapped[DateType] = mapped_column(Date)
    counterparty: Mapped[str] = mapped_column(String(180), default="")
    amount: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("company_id", "number", name="uq_generated_doc_company_number"), CheckConstraint("amount >= 0"))

class AIAction(Record, Base):
    __tablename__ = "ai_actions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("ai_threads.id", ondelete="SET NULL"), nullable=True)
    agent: Mapped[str] = mapped_column(String(30), default="rick")
    action_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    risk: Mapped[str] = mapped_column(String(20), default="high")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")

Index("ix_ai_actions_pending", AIAction.status, AIAction.user_id, AIAction.created_at)

class AIActionPlan(Record, Base):
    __tablename__ = "ai_action_plans"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    thread_id: Mapped[int | None] = mapped_column(ForeignKey("ai_threads.id", ondelete="SET NULL"), nullable=True)
    agent: Mapped[str] = mapped_column(String(30), default="rick")
    title: Mapped[str] = mapped_column(String(180), default="AI-план")
    goal: Mapped[str] = mapped_column(Text, default="")
    steps: Mapped[list] = mapped_column(JSON, default=list)
    action_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AccountExchangeRate(Record, Base):
    __tablename__ = 'account_exchange_rates'
    account_id: Mapped[int] = mapped_column(ForeignKey('accounts.id'))
    currency: Mapped[str] = mapped_column(String(3))
    rate_date: Mapped[DateType] = mapped_column(Date)
    rate_scaled: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(80), default='manual_confirmed')
    __table_args__ = (UniqueConstraint('account_id','currency','rate_date'),CheckConstraint('rate_scaled > 0'))
