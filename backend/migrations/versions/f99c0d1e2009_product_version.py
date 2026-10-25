"""Add optimistic concurrency token to catalog products."""
from alembic import op
import sqlalchemy as sa

revision = "f99c0d1e2009"
down_revision = "f98b9c1d2008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("products", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    op.drop_column("products", "version")
