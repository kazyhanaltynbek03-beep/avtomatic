"""expand marketplace sync cursor for durable per-section state"""
from alembic import op
import sqlalchemy as sa
revision="d31f4a6b7001"
down_revision="c20e3f405002"
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind(); i=sa.inspect(bind)
    if not i.has_table("accounts"): return
    cols={c["name"]:c for c in i.get_columns("accounts")}
    if "sync_cursor" not in cols:
        op.add_column("accounts",sa.Column("sync_cursor",sa.Text(),nullable=False,server_default="")); return
    if bind.dialect.name=="sqlite": return
    typ=cols["sync_cursor"]["type"]
    if not isinstance(typ, sa.Text): op.alter_column("accounts","sync_cursor",existing_type=typ,type_=sa.Text(),existing_nullable=cols["sync_cursor"].get("nullable",False))

def downgrade():
    bind=op.get_bind(); i=sa.inspect(bind)
    if not i.has_table("accounts") or bind.dialect.name=="sqlite": return
    cols={c["name"]:c for c in i.get_columns("accounts")}
    if "sync_cursor" in cols: op.alter_column("accounts","sync_cursor",existing_type=cols["sync_cursor"]["type"],type_=sa.String(300),existing_nullable=cols["sync_cursor"].get("nullable",False))
