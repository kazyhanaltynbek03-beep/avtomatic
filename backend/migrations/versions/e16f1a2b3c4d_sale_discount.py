"""store sale discount separately while recognising net revenue"""
from alembic import op
import sqlalchemy as sa

revision = "e16f1a2b3c4d"
down_revision = "d15e0a1b2c3d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sales", sa.Column("discount", sa.BigInteger(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("sales", "discount")
