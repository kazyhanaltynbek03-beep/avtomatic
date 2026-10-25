"""marketplace sync state"""
from alembic import op
import sqlalchemy as sa
revision = "c91e77d2a4b0"
down_revision = "b7c1f2e4a901"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("accounts", sa.Column("sync_status", sa.String(length=20), nullable=False, server_default="never"))
    op.add_column("accounts", sa.Column("sync_error", sa.String(length=500), nullable=False, server_default=""))
    op.add_column("accounts", sa.Column("sync_cursor", sa.String(length=300), nullable=False, server_default=""))

def downgrade():
    op.drop_column("accounts", "sync_cursor")
    op.drop_column("accounts", "sync_error")
    op.drop_column("accounts", "sync_status")
