"""idempotent marketplace staging ledger"""
from alembic import op
import sqlalchemy as sa
revision='d15e0a1b2c3d'; down_revision='f95a6c3e5005'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('marketplace_records',
        sa.Column('account_id',sa.Integer(),sa.ForeignKey('accounts.id'),nullable=False),
        sa.Column('company_id',sa.Integer(),sa.ForeignKey('companies.id'),nullable=False),
        sa.Column('source',sa.String(30),nullable=False),
        sa.Column('external_id',sa.String(160),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),
        sa.Column('status',sa.String(20),nullable=False,server_default='received'),
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('account_id','source','external_id',name='uq_marketplace_record_external'))
    op.create_index('ix_marketplace_records_account_id','marketplace_records',['account_id'])
    op.create_index('ix_marketplace_records_company_id','marketplace_records',['company_id'])

def downgrade():
    op.drop_index('ix_marketplace_records_company_id',table_name='marketplace_records')
    op.drop_index('ix_marketplace_records_account_id',table_name='marketplace_records')
    op.drop_table('marketplace_records')
