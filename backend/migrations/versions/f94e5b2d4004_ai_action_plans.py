"""AI multi-step action plans
Revision ID: f94e5b2d4004
Revises: f93e4a1c3003
"""
from alembic import op
import sqlalchemy as sa
revision='f94e5b2d4004'; down_revision='f93e4a1c3003'; branch_labels=None; depends_on=None
def upgrade():
    op.create_table('ai_action_plans',
      sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
      sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('company_id',sa.Integer(),sa.ForeignKey('companies.id'),nullable=True),
      sa.Column('thread_id',sa.Integer(),sa.ForeignKey('ai_threads.id',ondelete='SET NULL'),nullable=True),sa.Column('agent',sa.String(30),nullable=False,server_default='rick'),
      sa.Column('title',sa.String(180),nullable=False,server_default='AI-план'),sa.Column('goal',sa.Text(),nullable=False,server_default=''),
      sa.Column('steps',sa.JSON(),nullable=False),sa.Column('action_ids',sa.JSON(),nullable=False),sa.Column('status',sa.String(20),nullable=False,server_default='pending'),
      sa.Column('progress',sa.Integer(),nullable=False,server_default='0'),sa.Column('result',sa.JSON(),nullable=False),sa.Column('error',sa.Text(),nullable=False,server_default=''),
      sa.Column('confirmed_at',sa.DateTime(timezone=True),nullable=True),sa.Column('executed_at',sa.DateTime(timezone=True),nullable=True))
    op.create_index('ix_ai_action_plans_user_id','ai_action_plans',['user_id']); op.create_index('ix_ai_action_plans_company_id','ai_action_plans',['company_id'])
def downgrade():
    op.drop_index('ix_ai_action_plans_company_id',table_name='ai_action_plans'); op.drop_index('ix_ai_action_plans_user_id',table_name='ai_action_plans'); op.drop_table('ai_action_plans')
