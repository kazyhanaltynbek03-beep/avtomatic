"""encrypted marketplace credentials"""
from alembic import op
import sqlalchemy as sa
revision='f95a6c3e5005'; down_revision='aa0b1c2d3e4f'; branch_labels=None; depends_on=None

def upgrade():
    op.create_table('integration_secrets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False),
        sa.Column('encrypted_payload', sa.Text(), nullable=False),
        sa.Column('key_hint', sa.String(12), nullable=False, server_default=''))
    op.create_index('ix_integration_secrets_account_id','integration_secrets',['account_id'],unique=True)

def downgrade():
    op.drop_index('ix_integration_secrets_account_id', table_name='integration_secrets')
    op.drop_table('integration_secrets')
