"""Separate master SKUs from existing marketplace catalogue records.

Existing product rows remain intact so sales, batches, returns and audit history
continue to reference the same IDs. Rows already used by marketplace mappings
move to the marketplace catalogue; new products default to master SKUs.
"""
from alembic import op
import sqlalchemy as sa

revision = "9f1d8a7c6b55"
down_revision = "8b4f2a1c9001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "products",
        sa.Column("catalog_kind", sa.String(length=20), nullable=False, server_default="master"),
    )
    op.execute(
        "UPDATE products SET catalog_kind = 'marketplace' "
        "WHERE id IN (SELECT DISTINCT product_id FROM marketplace_product_mappings)"
    )


def downgrade():
    op.drop_column("products", "catalog_kind")
