"""Analysis checkpoints, immutable releases and reproducible scenario evaluations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def identity():
    return sa.Column('id', sa.Uuid(), primary_key=True)


def created():
    return sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade():
    op.create_table('analysis_runs', identity(), sa.Column('guide_id', sa.Uuid(), sa.ForeignKey('guides.id'), nullable=False),
                    sa.Column('status', sa.String(30), nullable=False), sa.Column('version', sa.Integer(), nullable=False),
                    sa.Column('config', JSONB(), nullable=False), sa.Column('payload', JSONB(), nullable=False), sa.Column('error', sa.Text()), created())
    op.create_index('ix_analysis_runs_guide_id', 'analysis_runs', ['guide_id'])
    op.create_table('rule_releases', identity(), sa.Column('retailer_id', sa.String(50), sa.ForeignKey('retailers.id'), nullable=False),
                    sa.Column('run_id', sa.Uuid(), sa.ForeignKey('analysis_runs.id'), nullable=False, unique=True),
                    sa.Column('name', sa.String(200), nullable=False), sa.Column('effective_date', sa.Date(), nullable=False), sa.Column('payload', JSONB(), nullable=False), created())
    op.create_index('ix_rule_releases_retailer_id', 'rule_releases', ['retailer_id'])
    op.create_table('release_heads', sa.Column('retailer_id', sa.String(50), sa.ForeignKey('retailers.id'), primary_key=True), sa.Column('release_id', sa.Uuid(), sa.ForeignKey('rule_releases.id')))
    op.execute('INSERT INTO release_heads(retailer_id) SELECT id FROM retailers')
    op.create_table('scenarios', identity(), sa.Column('retailer_id', sa.String(50), sa.ForeignKey('retailers.id'), nullable=False), sa.Column('name', sa.String(200), nullable=False), sa.Column('payload', JSONB(), nullable=False), created())
    op.create_index('ix_scenarios_retailer_id', 'scenarios', ['retailer_id'])
    op.create_table('evaluations', identity(), sa.Column('scenario_id', sa.Uuid(), sa.ForeignKey('scenarios.id'), nullable=False), sa.Column('release_id', sa.Uuid(), sa.ForeignKey('rule_releases.id'), nullable=False), sa.Column('payload', JSONB(), nullable=False), created())
    op.create_table('audit_events', identity(), sa.Column('entity_id', sa.Uuid(), nullable=False), sa.Column('actor', sa.String(200), nullable=False), sa.Column('action', sa.String(100), nullable=False), sa.Column('payload', JSONB(), nullable=False), created())
    op.create_index('ix_audit_events_entity_id', 'audit_events', ['entity_id'])


def downgrade():
    for name in ('audit_events', 'evaluations', 'scenarios', 'release_heads', 'rule_releases', 'analysis_runs'):
        op.drop_table(name)
