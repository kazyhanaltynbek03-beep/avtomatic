"""Add return inspection state and batch allocation links.

Revision ID: f98b9c1d2008
Revises: c2f5a8d1e300

Existing returns are marked restocked for compatibility; new returns default to
requested. The table links a return to its original FIFO batches so restocking
can be idempotent after inspection.
"""
from alembic import op
import sqlalchemy as sa

revision = "f98b9c1d2008"
down_revision = "c2f5a8d1e300"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "returns",
        sa.Column(
            "inventory_status",
            sa.String(length=30),
            nullable=False,
            server_default="requested",
        ),
    )
    # Old returns were restocked by the previous posting logic; backfill them.
    op.execute("UPDATE returns SET inventory_status = 'restocked'")
    op.create_table(
        "return_inventory_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("return_id", sa.Integer(), sa.ForeignKey("returns.id"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("batches.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("cost", sa.BigInteger(), nullable=False),
        sa.Column("restocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0 AND cost >= 0"),
        sa.UniqueConstraint("return_id", "batch_id", name="uq_return_inventory_return_batch"),
    )
    op.create_index("ix_return_inventory_allocations_return_id", "return_inventory_allocations", ["return_id"])
    op.create_index("ix_return_inventory_allocations_batch_id", "return_inventory_allocations", ["batch_id"])


def downgrade():
    # Retain additive return audit data during rollback; old app versions ignore it.
    pass
