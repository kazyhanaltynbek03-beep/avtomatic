"""Immutable operation FX and explicit pipeline progress; preserve existing ledgers."""
from alembic import op
import sqlalchemy as sa
revision="c20e3f405002"
down_revision="b19d2e3f4001"
branch_labels=None
depends_on=None

def _cols(t): return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(t)}
def upgrade():
    for table in ("sales","expenses"):
        if "source_fx" not in _cols(table): op.add_column(table,sa.Column("source_fx",sa.JSON(),nullable=False,server_default="{}"))
    if "stage_status" not in _cols("marketplace_records"): op.add_column("marketplace_records",sa.Column("stage_status",sa.String(30),nullable=False,server_default="received"))
    if "reason_code" not in _cols("marketplace_records"): op.add_column("marketplace_records",sa.Column("reason_code",sa.String(100),nullable=False,server_default=""))
    if not sa.inspect(op.get_bind()).has_table("account_exchange_rates"):
        op.create_table("account_exchange_rates",sa.Column("id",sa.Integer(),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("account_id",sa.Integer(),sa.ForeignKey("accounts.id"),nullable=False),sa.Column("currency",sa.String(3),nullable=False),sa.Column("rate_date",sa.Date(),nullable=False),sa.Column("rate_scaled",sa.BigInteger(),nullable=False),sa.Column("source",sa.String(80),nullable=False),sa.UniqueConstraint("account_id","currency","rate_date"),sa.CheckConstraint("rate_scaled > 0"))

def downgrade():
    if sa.inspect(op.get_bind()).has_table("account_exchange_rates"): op.drop_table("account_exchange_rates")
    for col in ("reason_code","stage_status"):
        if col in _cols("marketplace_records"): op.drop_column("marketplace_records",col)
    for table in ("sales","expenses"):
        if "source_fx" in _cols(table): op.drop_column(table,"source_fx")
