"""Add scheduled daily report settings and delivery log."""
from alembic import op
import sqlalchemy as sa


revision = "fa88d1a42011"
down_revision = "d68e0f3b9a21"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("settings", sa.Column("daily_report_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("settings", sa.Column("daily_report_time", sa.String(length=5), nullable=False, server_default="09:00"))
    op.add_column("settings", sa.Column("daily_report_recipient", sa.String(length=32), nullable=False, server_default=""))
    op.add_column("settings", sa.Column("daily_report_consent", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("settings", sa.Column("daily_report_ai_summary", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "daily_report_deliveries",
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("recipient", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False, server_default="whatsapp_cloud"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=180), nullable=False, server_default=""),
        sa.Column("error", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "report_date", "recipient", "provider", name="uq_daily_report_delivery"),
    )
    op.create_index("ix_daily_report_deliveries_company_id", "daily_report_deliveries", ["company_id"])
    op.create_index("ix_daily_report_deliveries_report_date", "daily_report_deliveries", ["report_date"])


def downgrade():
    op.drop_index("ix_daily_report_deliveries_report_date", table_name="daily_report_deliveries")
    op.drop_index("ix_daily_report_deliveries_company_id", table_name="daily_report_deliveries")
    op.drop_table("daily_report_deliveries")
    op.drop_column("settings", "daily_report_ai_summary")
    op.drop_column("settings", "daily_report_consent")
    op.drop_column("settings", "daily_report_recipient")
    op.drop_column("settings", "daily_report_time")
    op.drop_column("settings", "daily_report_enabled")
