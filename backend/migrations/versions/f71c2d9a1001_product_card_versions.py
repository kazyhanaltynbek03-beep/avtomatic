"""product card versions
Revision ID: f71c2d9a1001
Revises: e52f4a91c0d2
"""
from alembic import op
import sqlalchemy as sa
revision='f71c2d9a1001'; down_revision='e52f4a91c0d2'; branch_labels=None; depends_on=None
def upgrade():
    op.create_table('product_card_versions',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False),sa.Column('company_id',sa.Integer(),sa.ForeignKey('companies.id'),nullable=False),sa.Column('product_id',sa.Integer(),sa.ForeignKey('products.id'),nullable=False),sa.Column('marketplace',sa.String(20),nullable=False),sa.Column('version',sa.Integer(),nullable=False),sa.Column('title',sa.String(240),nullable=False),sa.Column('description',sa.Text(),nullable=False),sa.Column('characteristics',sa.JSON(),nullable=False),sa.Column('image_document_ids',sa.JSON(),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('validation',sa.JSON(),nullable=False),sa.Column('metrics',sa.JSON(),nullable=False),sa.Column('published_at',sa.DateTime(timezone=True)),sa.Column('review_after',sa.DateTime(timezone=True)),sa.Column('parent_version_id',sa.Integer(),sa.ForeignKey('product_card_versions.id')))
    op.create_index('ix_product_card_product_market','product_card_versions',['product_id','marketplace','version'])
def downgrade():
    op.drop_index('ix_product_card_product_market',table_name='product_card_versions'); op.drop_table('product_card_versions')
