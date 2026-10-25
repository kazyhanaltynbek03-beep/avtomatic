"""Persist seller-scoped, effective-dated Wildberries unit costs."""
from alembic import op
import sqlalchemy as sa

revision = "c1e4a7b90210"
down_revision = "f8c3a2b1d901"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("marketplace_product_costs"):
        return
    op.create_table(
        "marketplace_product_costs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("external_key", sa.String(200), nullable=False),
        sa.Column("nm_id", sa.String(40), nullable=False, server_default=""),
        sa.Column("seller_article", sa.String(120), nullable=False, server_default=""),
        sa.Column("barcode", sa.String(80), nullable=False, server_default=""),
        sa.Column("product_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("unit_cost", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KZT"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("account_id", "external_key", "effective_from", name="uq_wb_cost_effective"),
        sa.CheckConstraint("unit_cost > 0", name="ck_marketplace_product_costs_unit_cost"),
    )
    op.create_index("ix_marketplace_product_costs_company_id", "marketplace_product_costs", ["company_id"])
    op.create_index("ix_marketplace_product_costs_account_id", "marketplace_product_costs", ["account_id"])
    op.create_index("ix_marketplace_product_costs_effective_from", "marketplace_product_costs", ["effective_from"])


def downgrade():
    op.drop_table("marketplace_product_costs")
