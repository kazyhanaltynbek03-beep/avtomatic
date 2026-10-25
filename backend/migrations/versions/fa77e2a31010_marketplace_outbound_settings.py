"""Store additive per-marketplace outbound settings."""
from alembic import op
import sqlalchemy as sa

revision = "fa77e2a31010"
down_revision = "f99c0d1e2009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("accounts", sa.Column(
        "integration_settings", sa.JSON(), nullable=False,
        server_default=sa.text("'{}'"),
    ))


def downgrade():
    op.drop_column("accounts", "integration_settings")
