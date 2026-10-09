"""Treat missing embedded text as informational, preserving actual failures."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

OLD_NOTICE = "No text was extracted. This page may be scanned, image-only or blank; inspect the original."


def refresh_counts():
    op.execute("""
        UPDATE guides SET attention_pages = (
            SELECT count(*) FROM guide_pages
            WHERE guide_pages.guide_id = guides.id AND issue IS NOT NULL
        )
    """)
    # Never promote incomplete or failed jobs to ready.
    op.execute("""
        UPDATE guides
        SET status = CASE WHEN attention_pages > 0 THEN 'needs_attention' ELSE 'ready' END
        WHERE status IN ('ready', 'needs_attention')
    """)


def upgrade():
    op.get_bind().execute(sa.text("""
        UPDATE guide_pages
        SET issue = NULLIF(trim(replace(issue, :notice, '')), '')
        WHERE text_status = 'no_text'
    """), {"notice": OLD_NOTICE})
    refresh_counts()


def downgrade():
    op.get_bind().execute(sa.text("""
        UPDATE guide_pages
        SET issue = :notice || CASE WHEN issue IS NULL THEN '' ELSE ' ' || issue END
        WHERE text_status = 'no_text'
    """), {"notice": OLD_NOTICE})
    refresh_counts()
