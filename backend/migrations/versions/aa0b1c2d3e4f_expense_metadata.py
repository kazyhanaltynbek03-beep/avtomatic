"""Add expense project and payment method metadata.

Revision ID: aa0b1c2d3e4f
Revises: f94e5b2d4004
"""
from alembic import op
import sqlalchemy as sa

revision = "aa0b1c2d3e4f"
down_revision = "f94e5b2d4004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("expenses", sa.Column("project", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("expenses", sa.Column("payment_method", sa.String(length=60), nullable=False, server_default=""))


def downgrade():
    op.drop_column("expenses", "payment_method")
    op.drop_column("expenses", "project")
