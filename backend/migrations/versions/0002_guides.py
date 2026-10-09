"""Immutable guide uploads and per-page preparation coverage."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "guides",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("retailer_id", sa.String(50), sa.ForeignKey("retailers.id"), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("version_label", sa.String(100)),
        sa.Column("effective_date", sa.Date()),
        sa.Column("filename", sa.String(250), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(30), server_default="queued", nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column("processed_pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attention_pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("retailer_id", "sha256", name="uq_guide_retailer_hash"),
    )
    op.create_index("ix_guides_retailer_id", "guides", ["retailer_id"])
    op.create_index("ix_guides_created_at", "guides", ["created_at"])
    op.create_table(
        "guide_pages",
        sa.Column("guide_id", sa.Uuid(), sa.ForeignKey("guides.id"), primary_key=True),
        sa.Column("page_index", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text()),
        sa.Column("text_status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("image_status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("issue", sa.Text()),
    )


def downgrade():
    op.drop_table("guide_pages")
    op.drop_table("guides")
