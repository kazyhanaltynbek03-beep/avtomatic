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
    with op.batch_alter_table("movements") as batch:
        batch.alter_column("batch_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    # Pending marketplace quantity movements can have no purchase batch. Keep
    # the field nullable until those rows have been reconciled.
    with op.batch_alter_table("movements") as batch:
        batch.alter_column("batch_id", existing_type=sa.Integer(), nullable=True)
