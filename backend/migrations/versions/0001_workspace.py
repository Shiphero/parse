"""Workspace records and initial retailer catalog."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    retailers = op.create_table(
        "retailers",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("discovery_note", sa.Text(), nullable=False),
    )
    op.create_table(
        "service_heartbeats",
        sa.Column("service", sa.String(100), primary_key=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.bulk_insert(retailers, [
        {"id": "nordstrom", "name": "Nordstrom", "discovery_note": "Routing and ASN references identified. Historical material needs separate authority review."},
        {"id": "walmart", "name": "Walmart", "discovery_note": "Secondary packaging excerpt identified. Full routing coverage is still needed."},
        {"id": "ulta", "name": "Ulta Beauty", "discovery_note": "Supply chain and ASN references identified. First planned end-to-end workflow."},
        {"id": "michaels", "name": "Michaels", "discovery_note": "EDI references identified. The full routing and label manual is still needed."},
    ])


def downgrade():
    op.drop_table("service_heartbeats")
    op.drop_table("retailers")
