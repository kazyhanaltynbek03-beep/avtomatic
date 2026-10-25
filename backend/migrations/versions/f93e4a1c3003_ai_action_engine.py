"""AI action engine with explicit approvals
Revision ID: f93e4a1c3003
Revises: f82d3e1b2002
"""
from alembic import op
import sqlalchemy as sa
revision='f93e4a1c3003'; down_revision='f82d3e1b2002'; branch_labels=None; depends_on=None
def upgrade():
    op.create_table('ai_actions',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('company_id',sa.Integer(),sa.ForeignKey('companies.id'),nullable=True),sa.Column('thread_id',sa.Integer(),sa.ForeignKey('ai_threads.id',ondelete='SET NULL'),nullable=True),sa.Column('agent',sa.String(30),nullable=False,server_default='rick'),sa.Column('action_type',sa.String(60),nullable=False),sa.Column('payload',sa.JSON(),nullable=False),sa.Column('preview',sa.JSON(),nullable=False),sa.Column('risk',sa.String(20),nullable=False,server_default='high'),sa.Column('status',sa.String(20),nullable=False,server_default='pending'),sa.Column('result',sa.JSON(),nullable=False),sa.Column('confirmed_at',sa.DateTime(timezone=True),nullable=True),sa.Column('executed_at',sa.DateTime(timezone=True),nullable=True),sa.Column('error',sa.Text(),nullable=False,server_default=''))
    op.create_index('ix_ai_actions_user_id','ai_actions',['user_id']); op.create_index('ix_ai_actions_company_id','ai_actions',['company_id']); op.create_index('ix_ai_actions_pending','ai_actions',['status','user_id','created_at'])
def downgrade():
    op.drop_index('ix_ai_actions_pending',table_name='ai_actions'); op.drop_index('ix_ai_actions_company_id',table_name='ai_actions'); op.drop_index('ix_ai_actions_user_id',table_name='ai_actions'); op.drop_table('ai_actions')
