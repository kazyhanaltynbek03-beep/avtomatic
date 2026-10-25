"""Allow marketplace accounts to be archived without removing their ledger."""
from alembic import op
import sqlalchemy as sa


revision = "c2f5a8d1e300"
down_revision = "c1e4a7b90210"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("accounts", "active")
