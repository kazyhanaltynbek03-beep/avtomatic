"""Restore the production Alembic revision marker used by existing Render DBs.

Revision ID: f97c8e5f7007
Revises: f96b7d4e6006

This revision intentionally performs no DDL. It is a compatibility bridge: an
older production release stamped databases with this revision, while a later
source cleanup accidentally removed the revision file. Keeping the marker in
the graph lets those databases continue upgrading without destructive stamping
or database resets.
"""
revision = "f97c8e5f7007"
down_revision = "f96b7d4e6006"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
