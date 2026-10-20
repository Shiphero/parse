"""Persist normalized retailer icons and their cache versions."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('retailers', sa.Column('icon_png', sa.LargeBinary(), nullable=True))
    op.add_column('retailers', sa.Column('icon_version', sa.String(64), nullable=True))


def downgrade():
    op.drop_column('retailers', 'icon_version')
    op.drop_column('retailers', 'icon_png')
