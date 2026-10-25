"""Allow signed Marketplace fee corrections while keeping ordinary expenses positive."""
from alembic import op
import sqlalchemy as sa

revision = "f8c3a2b1d901"
down_revision = "d31f4a6b7001"
branch_labels = None
depends_on = None


def _positive_check():
    checks = sa.inspect(op.get_bind()).get_check_constraints("expenses")
    for check in checks:
        expression = "".join(str(check.get("sqltext") or "").lower().split()).replace('"', "")
        if expression in {"amount>0", "(amount>0)"}:
            return check
    return None


def upgrade():
    check = _positive_check()
    if not check:
        return
    if op.get_bind().dialect.name == "sqlite":
        # Initial SQLite migrations created this CHECK unnamed. The temporary
        # naming convention gives Alembic's batch copier a stable drop handle.
        convention = {"ck": "ck_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("expenses", naming_convention=convention) as batch:
            batch.drop_constraint(check.get("name") or "ck_expenses_amount", type_="check")
            batch.create_check_constraint("ck_expenses_amount_nonzero", "amount != 0")
    else:
        op.drop_constraint(check["name"], "expenses", type_="check")
        op.create_check_constraint("ck_expenses_amount_nonzero", "expenses", "amount != 0")


def downgrade():
    bind = op.get_bind()
    negative_count = bind.execute(sa.text("SELECT count(*) FROM expenses WHERE amount < 0")).scalar_one()
    if negative_count:
        raise RuntimeError("Cannot restore positive-only expense constraint while signed marketplace corrections exist")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("expenses") as batch:
            batch.drop_constraint("ck_expenses_amount_nonzero", type_="check")
            batch.create_check_constraint("ck_expenses_amount_positive", "amount > 0")
    else:
        op.drop_constraint("ck_expenses_amount_nonzero", "expenses", type_="check")
        op.create_check_constraint("ck_expenses_amount_positive", "expenses", "amount > 0")
