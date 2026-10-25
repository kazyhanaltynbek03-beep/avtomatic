"""persistent AI workspace chats"""
from alembic import op
import sqlalchemy as sa
revision = "e52f4a91c0d2"
down_revision = "d41a8f0c2e11"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("ai_threads",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("agent", sa.String(30), nullable=False, server_default="rick"),
        sa.Column("title", sa.String(180), nullable=False, server_default="Новый чат"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_ai_threads_user", "ai_threads", ["user_id", "archived", "id"])
    op.create_table("ai_messages",
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("ai_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user','assistant','system')"))
    op.create_index("ix_ai_messages_thread", "ai_messages", ["thread_id", "id"])

def downgrade():
    op.drop_table("ai_messages")
    op.drop_table("ai_threads")
