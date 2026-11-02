"""Precomputed dashboard report snapshots."""
from alembic import op
import sqlalchemy as sa


revision = "b1e5f8c21001"
down_revision = "fa88d1a42011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dashboard_report_cache",
        sa.Column("scope_key", sa.String(length=120), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_key", "start_date", "end_date", name="uq_dashboard_report_cache_range"),
    )
    op.create_index(
        "ix_dashboard_report_cache_created_at",
        "dashboard_report_cache",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_dashboard_report_cache_created_at", table_name="dashboard_report_cache")
    op.drop_table("dashboard_report_cache")
