"""Store editable cost and tax rate for product reports."""
from alembic import op
import sqlalchemy as sa


revision = "d68e0f3b9a21"
down_revision = "d57c9e1a4b20"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "marketplace_product_report_settings",
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("unit_cost_cents", sa.BigInteger(), nullable=True),
        sa.Column("tax_rate_bps", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "product_id", name="uq_marketplace_product_report_setting"),
        sa.CheckConstraint("unit_cost_cents IS NULL OR unit_cost_cents >= 0"),
        sa.CheckConstraint("tax_rate_bps IS NULL OR (tax_rate_bps >= 0 AND tax_rate_bps <= 10000)"),
    )
    op.create_index(
        "ix_marketplace_product_report_settings_company_id",
        "marketplace_product_report_settings", ["company_id"],
    )
    op.create_index(
        "ix_marketplace_product_report_settings_product_id",
        "marketplace_product_report_settings", ["product_id"],
    )


def downgrade():
    op.drop_index("ix_marketplace_product_report_settings_product_id",
                  table_name="marketplace_product_report_settings")
    op.drop_index("ix_marketplace_product_report_settings_company_id",
                  table_name="marketplace_product_report_settings")
    op.drop_table("marketplace_product_report_settings")
