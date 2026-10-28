"""Add an isolated marketplace returns observation ledger.

This migration only creates new tables and indexes. It does not update or
backfill the financial ``returns`` table and cannot change existing reports.
"""
from alembic import op
import sqlalchemy as sa

revision = "8b4f2a1c9001"
down_revision = "fa77e2a31010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "marketplace_returns",
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("marketplace", sa.String(20), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("external_return_id", sa.String(200), nullable=False),
        sa.Column("external_order_id", sa.String(160), nullable=False, server_default=""),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("product_name", sa.String(240), nullable=False, server_default=""),
        sa.Column("sku", sa.String(120), nullable=False, server_default=""),
        sa.Column("image_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("request_date", sa.Date(), nullable=True),
        sa.Column("financial_return_date", sa.Date(), nullable=True),
        sa.Column("detected_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KZT"),
        sa.Column("return_status", sa.String(40), nullable=False, server_default="detected"),
        sa.Column("financial_status", sa.String(30), nullable=False, server_default="unconfirmed"),
        sa.Column("accounted_status", sa.String(20), nullable=False, server_default="unverified"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("guarantee_case", sa.Boolean(), nullable=True),
        sa.Column("defect", sa.Text(), nullable=False, server_default=""),
        sa.Column("examination", sa.Text(), nullable=False, server_default=""),
        sa.Column("seller_decision", sa.Text(), nullable=False, server_default=""),
        sa.Column("marketplace_decision", sa.Text(), nullable=False, server_default=""),
        sa.Column("item_condition", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("raw_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "source", "external_return_id", name="uq_marketplace_return_identity"),
        sa.CheckConstraint("quantity IS NULL OR quantity > 0", name="ck_marketplace_returns_quantity"),
        sa.CheckConstraint("amount IS NULL OR amount >= 0", name="ck_marketplace_returns_amount"),
        sa.CheckConstraint("accounted_status IN ('yes','no','unverified')", name="ck_marketplace_returns_accounted"),
    )
    op.create_index("ix_marketplace_returns_company_id", "marketplace_returns", ["company_id"])
    op.create_index("ix_marketplace_returns_account_id", "marketplace_returns", ["account_id"])
    op.create_index("ix_marketplace_returns_marketplace", "marketplace_returns", ["marketplace"])
    op.create_index("ix_marketplace_returns_financial_date", "marketplace_returns", ["financial_return_date"])
    op.create_index("ix_marketplace_returns_request_date", "marketplace_returns", ["request_date"])
    op.create_table(
        "marketplace_return_audits",
        sa.Column("return_id", sa.Integer(), sa.ForeignKey("marketplace_returns.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_marketplace_return_audits_return_id", "marketplace_return_audits", ["return_id"])
    op.create_table(
        "marketplace_return_sync_states",
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="never"),
        sa.Column("cursor", sa.String(200), nullable=False, server_default=""),
        sa.Column("scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_marketplace_return_sync_states_account_id", "marketplace_return_sync_states", ["account_id"])


def downgrade():
    # Keep this ledger across rollback; existing app versions ignore these tables.
    pass
