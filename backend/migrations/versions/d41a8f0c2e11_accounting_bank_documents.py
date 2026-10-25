"""accounting bank counterparties tax rules generated documents"""
from alembic import op
import sqlalchemy as sa
revision = "d41a8f0c2e11"
down_revision = "c91e77d2a4b0"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("counterparties", sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("name", sa.String(180), nullable=False), sa.Column("bin", sa.String(12), nullable=False, server_default=""), sa.Column("kind", sa.String(30), nullable=False, server_default="supplier"), sa.Column("notes", sa.Text(), nullable=False, server_default=""), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_counterparties_company", "counterparties", ["company_id"])
    op.create_table("bank_transactions", sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("reference", sa.String(140), nullable=False, unique=True), sa.Column("date", sa.Date(), nullable=False), sa.Column("account", sa.String(120), nullable=False), sa.Column("counterparty", sa.String(180), nullable=False, server_default=""), sa.Column("purpose", sa.Text(), nullable=False, server_default=""), sa.Column("direction", sa.String(10), nullable=False), sa.Column("amount", sa.BigInteger(), nullable=False), sa.Column("category", sa.String(80), nullable=False, server_default="uncategorized"), sa.Column("reconciled", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("amount > 0"), sa.CheckConstraint("direction IN ('in','out')"))
    op.create_index("ix_bank_company_date", "bank_transactions", ["company_id", "date"])
    op.create_table("tax_rules", sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("name", sa.String(160), nullable=False), sa.Column("rate_bps", sa.Integer(), nullable=False, server_default="0"), sa.Column("valid_from", sa.Date(), nullable=False), sa.Column("valid_to", sa.Date(), nullable=True), sa.Column("basis", sa.String(80), nullable=False, server_default="manual_review"), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("accountant_approved", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.CheckConstraint("rate_bps >= 0 AND rate_bps <= 10000"))
    op.create_index("ix_tax_rules_company", "tax_rules", ["company_id"])
    op.create_table("generated_documents", sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False), sa.Column("number", sa.String(80), nullable=False), sa.Column("kind", sa.String(40), nullable=False), sa.Column("date", sa.Date(), nullable=False), sa.Column("counterparty", sa.String(180), nullable=False, server_default=""), sa.Column("amount", sa.BigInteger(), nullable=False, server_default="0"), sa.Column("status", sa.String(30), nullable=False, server_default="draft"), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("company_id", "number", name="uq_generated_doc_company_number"), sa.CheckConstraint("amount >= 0"))
    op.create_index("ix_generated_docs_company", "generated_documents", ["company_id"])

def downgrade():
    op.drop_table("generated_documents"); op.drop_table("tax_rules"); op.drop_table("bank_transactions"); op.drop_table("counterparties")
