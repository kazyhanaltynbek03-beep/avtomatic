"""card auto optimization
Revision ID: f82d3e1b2002
Revises: f71c2d9a1001
"""
from alembic import op
import sqlalchemy as sa
revision='f82d3e1b2002'; down_revision='f71c2d9a1001'; branch_labels=None; depends_on=None

def upgrade():
    # f71 accidentally declared updated_at although the ORM never used it; keep DB/schema aligned.
    with op.batch_alter_table('product_card_versions') as b:
        b.drop_column('updated_at')
        b.add_column(sa.Column('optimization_policy', sa.JSON(), nullable=False, server_default='{}'))
        b.add_column(sa.Column('review_state', sa.String(30), nullable=False, server_default='idle'))
        b.add_column(sa.Column('last_reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_product_card_due_review','product_card_versions',['review_after','review_state'])

def downgrade():
    op.drop_index('ix_product_card_due_review',table_name='product_card_versions')
    with op.batch_alter_table('product_card_versions') as b:
        b.drop_column('last_reviewed_at'); b.drop_column('review_state'); b.drop_column('optimization_policy')
        b.add_column(sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
