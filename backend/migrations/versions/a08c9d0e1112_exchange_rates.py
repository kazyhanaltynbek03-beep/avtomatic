"""cache official historical FX rates"""
from alembic import op
import sqlalchemy as sa
revision="a08c9d0e1112"
down_revision="a07b8c9d1011"
branch_labels=None
depends_on=None

def upgrade():
    i=sa.inspect(op.get_bind())
    if not i.has_table("exchange_rates"):
        op.create_table("exchange_rates", sa.Column("id",sa.Integer(),primary_key=True), sa.Column("created_at",sa.DateTime(timezone=True),nullable=False), sa.Column("currency",sa.String(3),nullable=False), sa.Column("rate_date",sa.Date(),nullable=False), sa.Column("rate_scaled",sa.BigInteger(),nullable=False), sa.Column("source",sa.String(30),nullable=False,server_default="NBK"), sa.UniqueConstraint("currency","rate_date",name="uq_exchange_rate_currency_date"), sa.CheckConstraint("rate_scaled > 0"))
    names={x["name"] for x in sa.inspect(op.get_bind()).get_indexes("exchange_rates")}
    if "ix_exchange_rates_currency" not in names: op.create_index("ix_exchange_rates_currency","exchange_rates",["currency"])
    if "ix_exchange_rates_rate_date" not in names: op.create_index("ix_exchange_rates_rate_date","exchange_rates",["rate_date"])

def downgrade():
    if sa.inspect(op.get_bind()).has_table("exchange_rates"): op.drop_table("exchange_rates")
