"""full cost allocation and product master fields

Revision ID: b7c1f2e4a901
Revises: 90dae75ab0be
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c1f2e4a901"
down_revision = "90dae75ab0be"
branch_labels = None
depends_on = None

def upgrade():
    for name, typ, default in [
        ("article", sa.String(120), ""), ("brand", sa.String(120), ""),
        ("supplier", sa.String(160), ""), ("country", sa.String(100), ""),
        ("media", sa.JSON(), "[]"), ("currency", sa.String(3), "KZT"),
        ("fx_rate", sa.BigInteger(), "10000"), ("weight_g", sa.Integer(), "0"),
        ("volume_cm3", sa.Integer(), "0"), ("min_price", sa.BigInteger(), "0"),
        ("recommended_price", sa.BigInteger(), "0")]:
        op.add_column("products", sa.Column(name, typ, nullable=False, server_default=default))
    op.add_column("purchases", sa.Column("cost_breakdown", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("purchases", sa.Column("allocation_method", sa.String(20), nullable=False, server_default="value"))

def downgrade():
    op.drop_column("purchases", "allocation_method"); op.drop_column("purchases", "cost_breakdown")
    for name in ["recommended_price","min_price","volume_cm3","weight_g","fx_rate","currency","media","country","supplier","brand","article"]:
        op.drop_column("products", name)
