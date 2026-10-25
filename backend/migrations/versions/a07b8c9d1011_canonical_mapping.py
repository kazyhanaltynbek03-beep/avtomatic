"""Add scoped product aliases and canonical posting identities; preserve ledgers."""
from alembic import op
import sqlalchemy as sa
revision = "a07b8c9d1011"
down_revision = "f97c8e5f7007"
branch_labels = None
depends_on = None

def _insp(): return sa.inspect(op.get_bind())
def _cols(table):
    i=_insp(); return {c["name"] for c in i.get_columns(table)} if i.has_table(table) else set()
def _indexes(table):
    i=_insp(); return {x["name"] for x in i.get_indexes(table)} if i.has_table(table) else set()

def upgrade():
    if "settlement_currency" not in _cols("accounts"):
        op.add_column("accounts", sa.Column("settlement_currency", sa.String(3), nullable=False, server_default="KZT"))
    if "settlement_fx_rate" not in _cols("accounts"):
        op.add_column("accounts", sa.Column("settlement_fx_rate", sa.BigInteger(), nullable=False, server_default="10000"))
    if not _insp().has_table("marketplace_product_mappings"):
        op.create_table("marketplace_product_mappings",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False), sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("external_key", sa.String(200), nullable=False), sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.UniqueConstraint("account_id", "external_key", name="uq_marketplace_mapping"))
    if not _insp().has_table("canonical_events"):
        op.create_table("canonical_events",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id")),
            sa.Column("event_type", sa.String(30), nullable=False), sa.Column("identity", sa.String(200), nullable=False, unique=True),
            sa.Column("payload", sa.JSON(), nullable=False), sa.Column("target_id", sa.Integer()), sa.Column("status", sa.String(20), nullable=False))
    for table in ("marketplace_product_mappings", "canonical_events"):
        for col in ("company_id", "account_id"):
            name=f"ix_{table}_{col}"
            if name not in _indexes(table): op.create_index(name, table, [col])

def downgrade():
    # Downgrade remains conventional; production deploys only upgrade.
    if _insp().has_table("canonical_events"): op.drop_table("canonical_events")
    if _insp().has_table("marketplace_product_mappings"): op.drop_table("marketplace_product_mappings")
    if "settlement_fx_rate" in _cols("accounts"): op.drop_column("accounts", "settlement_fx_rate")
    if "settlement_currency" in _cols("accounts"): op.drop_column("accounts", "settlement_currency")
