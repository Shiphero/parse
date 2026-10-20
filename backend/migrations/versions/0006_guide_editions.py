"""Group immutable document editions without changing existing source IDs."""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('guides', sa.Column('series_id', sa.Uuid(), sa.ForeignKey('guides.id'), nullable=True))
    op.add_column('guides', sa.Column('previous_guide_id', sa.Uuid(), sa.ForeignKey('guides.id'), nullable=True))
    op.add_column('guides', sa.Column('edition_number', sa.Integer(), server_default='1', nullable=False))
    op.create_index('ix_guides_series_id', 'guides', ['series_id'])
    op.create_unique_constraint('uq_guide_series_edition', 'guides', ['series_id', 'edition_number'])
    op.create_unique_constraint('uq_guide_previous_edition', 'guides', ['previous_guide_id'])
    op.create_check_constraint('ck_guide_edition', 'guides',
        '(series_id IS NULL AND previous_guide_id IS NULL AND edition_number = 1) OR '
        '(series_id IS NOT NULL AND previous_guide_id IS NOT NULL AND edition_number > 1)')


def downgrade():
    op.drop_constraint('ck_guide_edition', 'guides')
    op.drop_constraint('uq_guide_previous_edition', 'guides')
    op.drop_constraint('uq_guide_series_edition', 'guides')
    op.drop_index('ix_guides_series_id', 'guides')
    op.drop_column('guides', 'edition_number')
    op.drop_column('guides', 'previous_guide_id')
    op.drop_column('guides', 'series_id')
