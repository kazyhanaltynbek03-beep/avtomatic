"""allow confirmed marketplace revenue before FIFO cost is available"""
from alembic import op
import sqlalchemy as sa
revision="b19d2e3f4001"
down_revision="a08c9d0e1112"
branch_labels=None
depends_on=None

def upgrade():
    cols={c["name"] for c in sa.inspect(op.get_bind()).get_columns("sales")}
    if "cogs_pending" not in cols: op.add_column("sales",sa.Column("cogs_pending",sa.Boolean(),nullable=False,server_default=sa.false()))

def downgrade():
    cols={c["name"] for c in sa.inspect(op.get_bind()).get_columns("sales")}
    if "cogs_pending" in cols: op.drop_column("sales","cogs_pending")
