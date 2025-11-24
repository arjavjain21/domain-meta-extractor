"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-11-24 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create domains table
    op.create_table('domains',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=False),
        sa.Column('normalized_domain', sa.String(length=255), nullable=False),
        sa.Column('meta_title', sa.String(length=500), nullable=True),
        sa.Column('meta_description', sa.Text(), nullable=True),
        sa.Column('extraction_method', sa.String(length=50), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('extraction_time', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('last_extracted', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cache_expires', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('extraction_count', sa.Integer(), nullable=True, default=0),
        sa.Column('success_count', sa.Integer(), nullable=True, default=0),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('domain'),
        sa.UniqueConstraint('normalized_domain')
    )

    # Create indexes for domains table
    op.create_index('idx_domains_normalized_domain', 'domains', ['normalized_domain'], unique=False)
    op.create_index('idx_domains_cache_expires', 'domains', ['cache_expires'], unique=False)
    op.create_index('idx_domains_last_extracted', 'domains', ['last_extracted'], unique=False)

    # Create jobs table
    op.create_table('jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True, default='pending'),
        sa.Column('total_domains', sa.Integer(), nullable=True),
        sa.Column('processed_domains', sa.Integer(), nullable=True, default=0),
        sa.Column('successful_domains', sa.Integer(), nullable=True, default=0),
        sa.Column('failed_domains', sa.Integer(), nullable=True, default=0),
        sa.Column('original_filename', sa.String(length=255), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('result_file_path', sa.String(length=500), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.Column('id').unique_argument('id')
    )

    # Create indexes for jobs table
    op.create_index('idx_jobs_status', 'jobs', ['status'], unique=False)
    op.create_index('idx_jobs_created_at', 'jobs', ['created_at'], unique=False)

    # Create extraction_stats table
    op.create_table('extraction_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('total_requests', sa.Integer(), nullable=True, default=0),
        sa.Column('successful_extractions', sa.Integer(), nullable=True, default=0),
        sa.Column('cache_hits', sa.Integer(), nullable=True, default=0),
        sa.Column('cache_misses', sa.Integer(), nullable=True, default=0),
        sa.Column('average_extraction_time', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('date')
    )

    # Create job_domains relationship table
    op.create_table('job_domains',
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('domain_id', sa.Integer(), nullable=False),
        sa.Column('original_row_index', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('job_id', 'domain_id')
    )

    # Create index for job_domains table
    op.create_index('idx_job_domains_status', 'job_domains', ['status'], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_index('idx_job_domains_status', table_name='job_domains')
    op.drop_table('job_domains')
    op.drop_table('extraction_stats')
    op.drop_index('idx_jobs_created_at', table_name='jobs')
    op.drop_index('idx_jobs_status', table_name='jobs')
    op.drop_table('jobs')
    op.drop_index('idx_domains_last_extracted', table_name='domains')
    op.drop_index('idx_domains_cache_expires', table_name='domains')
    op.drop_index('idx_domains_normalized_domain', table_name='domains')
    op.drop_table('domains')