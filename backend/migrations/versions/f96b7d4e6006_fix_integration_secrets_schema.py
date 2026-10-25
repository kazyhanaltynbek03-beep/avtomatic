"""align integration_secrets with ORM and fix production credential saves

Revision ID: f96b7d4e6006
Revises: e16f1a2b3c4d
"""
from alembic import op
import sqlalchemy as sa

revision = 'f96b7d4e6006'
down_revision = 'e16f1a2b3c4d'
branch_labels = None
depends_on = None


def upgrade():
    # f95 accidentally created updated_at as NOT NULL although IntegrationSecret
    # never had that ORM field. Production INSERTs therefore failed with an
    # IntegrityError (surfaced as HTTP 409). Remove the orphan column.
    with op.batch_alter_table('integration_secrets') as batch:
        batch.drop_column('updated_at')


def downgrade():
    with op.batch_alter_table('integration_secrets') as batch:
        batch.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
