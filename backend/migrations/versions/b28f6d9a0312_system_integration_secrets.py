"""Store Claude and WhatsApp credentials encrypted in the database."""
from alembic import op
import sqlalchemy as sa

revision = "b28f6d9a0312"
down_revision = "fa88d1a42011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "system_integration_secrets",
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("key_hint", sa.String(length=12), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider"),
    )


def downgrade():
    op.drop_table("system_integration_secrets")
