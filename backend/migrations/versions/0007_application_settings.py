"""Non-secret application preferences shared by API and worker."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('application_settings', sa.Column('name', sa.String(100), primary_key=True),
                    sa.Column('value', JSONB, nullable=False))


def downgrade():
    op.drop_table('application_settings')
