"""Allow confirmed marketplace sales to record quantity before FIFO cost is known.

Revision ID: b1c7d9e2a410
Revises: fa77e2a31010
"""
from alembic import op
import sqlalchemy as sa

revision = "b1c7d9e2a410"
down_revision = "9f1d8a7c6b55"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("movements", "batch_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    # Pending marketplace quantity movements can have no purchase batch. Refuse
    # to make the column mandatory until those rows have been reconciled.
    op.alter_column("movements", "batch_id", existing_type=sa.Integer(), nullable=True)
