"""Add company ownership links for shared product master records."""
from alembic import op
import sqlalchemy as sa
import json

revision = "d57c9e1a4b20"
down_revision = ("8b4f2a1c9001", "90dae75ab0be")
branch_labels = None
depends_on = None


def _as_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def upgrade():
    op.create_table(
        "product_companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.UniqueConstraint("product_id", "company_id", name="uq_product_company"),
    )
    op.create_index("ix_product_companies_product_id", "product_companies", ["product_id"])
    op.create_index("ix_product_companies_company_id", "product_companies", ["company_id"])

    bind = op.get_bind()
    metadata = sa.MetaData()
    products = sa.Table("products", metadata, autoload_with=bind)
    associations = set()

    # Preserve the explicit company list used by the product editor.
    for product_id, raw_specs in bind.execute(sa.select(products.c.id, products.c.specifications)):
        specs = _as_object(raw_specs)
        for value in specs.get("_qor_company_ids", []) or []:
            try:
                associations.add((int(product_id), int(value)))
            except (TypeError, ValueError):
                continue
        account_id = specs.get("account_id")
        if account_id is not None and "accounts" in sa.inspect(bind).get_table_names():
            accounts = sa.Table("accounts", metadata, autoload_with=bind)
            row = bind.execute(sa.select(accounts.c.company_id).where(accounts.c.id == account_id)).first()
            if row:
                associations.add((int(product_id), int(row[0])))

    # Historical inventory and financial events are authoritative ownership evidence.
    for table_name in ("batches", "sales", "marketplace_product_mappings", "movements", "product_card_versions"):
        if table_name not in sa.inspect(bind).get_table_names():
            continue
        table = sa.Table(table_name, metadata, autoload_with=bind)
        if {"product_id", "company_id"}.issubset(table.c.keys()):
            associations.update(
                (int(product_id), int(company_id))
                for product_id, company_id in bind.execute(
                    sa.select(table.c.product_id, table.c.company_id)
                    .where(table.c.product_id.is_not(None), table.c.company_id.is_not(None))
                )
            )

    if associations:
        now = sa.func.now()
        bind.execute(
            sa.insert(sa.Table("product_companies", metadata, autoload_with=bind)),
            [{"created_at": bind.execute(sa.select(now)).scalar_one(),
              "product_id": product_id, "company_id": company_id}
             for product_id, company_id in sorted(associations)],
        )


def downgrade():
    op.drop_index("ix_product_companies_company_id", table_name="product_companies")
    op.drop_index("ix_product_companies_product_id", table_name="product_companies")
    op.drop_table("product_companies")
