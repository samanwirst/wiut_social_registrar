"""Initial registration profiles, verification challenges, and analytics events."""
from alembic import op
import sqlalchemy as sa

revision = "0001_registration"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('outlook_profiles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.String(length=32), nullable=False),
    sa.Column('graph_id', sa.String(length=64), nullable=True),
    sa.Column('account', sa.String(length=320), nullable=False),
    sa.Column('display_name', sa.String(length=256), nullable=True),
    sa.Column('given_name', sa.String(length=256), nullable=True),
    sa.Column('surname', sa.String(length=256), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('email_addresses', sa.JSON(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('account')
    )
    op.create_index(op.f('ix_outlook_profiles_graph_id'), 'outlook_profiles', ['graph_id'], unique=False)
    op.create_index(op.f('ix_outlook_profiles_student_id'), 'outlook_profiles', ['student_id'], unique=False)
    op.create_table('telegram_users',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('first_name', sa.String(length=256), nullable=False),
    sa.Column('last_name', sa.String(length=256), nullable=True),
    sa.Column('username', sa.String(length=64), nullable=True),
    sa.Column('language_code', sa.String(length=35), nullable=True),
    sa.Column('is_premium', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('profile_updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('outlook_profile_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['outlook_profile_id'], ['outlook_profiles.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_telegram_users_last_seen_at'), 'telegram_users', ['last_seen_at'], unique=False)
    op.create_index(op.f('ix_telegram_users_outlook_profile_id'), 'telegram_users', ['outlook_profile_id'], unique=False)
    op.create_index(op.f('ix_telegram_users_username'), 'telegram_users', ['username'], unique=False)
    op.create_index(op.f('ix_telegram_users_verified_at'), 'telegram_users', ['verified_at'], unique=False)
    op.create_table('registration_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
    sa.Column('outlook_profile_id', sa.Integer(), nullable=True),
    sa.Column('event_type', sa.String(length=48), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['outlook_profile_id'], ['outlook_profiles.id'], ),
    sa.ForeignKeyConstraint(['telegram_user_id'], ['telegram_users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_events_profile_type_time', 'registration_events', ['outlook_profile_id', 'event_type', 'occurred_at'], unique=False)
    op.create_index('ix_events_user_type_time', 'registration_events', ['telegram_user_id', 'event_type', 'occurred_at'], unique=False)
    op.create_index(op.f('ix_registration_events_event_type'), 'registration_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_registration_events_occurred_at'), 'registration_events', ['occurred_at'], unique=False)
    op.create_table('verification_challenges',
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
    sa.Column('outlook_profile_id', sa.Integer(), nullable=False),
    sa.Column('nonce', sa.String(length=32), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('attempts_left', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('email_status', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['outlook_profile_id'], ['outlook_profiles.id'], ),
    sa.ForeignKeyConstraint(['telegram_user_id'], ['telegram_users.id'], ),
    sa.PrimaryKeyConstraint('telegram_user_id')
    )
    op.create_index(op.f('ix_verification_challenges_outlook_profile_id'), 'verification_challenges', ['outlook_profile_id'], unique=False)

def downgrade():
    op.drop_index(op.f('ix_verification_challenges_outlook_profile_id'), table_name='verification_challenges')
    op.drop_table('verification_challenges')
    op.drop_index(op.f('ix_registration_events_occurred_at'), table_name='registration_events')
    op.drop_index(op.f('ix_registration_events_event_type'), table_name='registration_events')
    op.drop_index('ix_events_user_type_time', table_name='registration_events')
    op.drop_index('ix_events_profile_type_time', table_name='registration_events')
    op.drop_table('registration_events')
    op.drop_index(op.f('ix_telegram_users_verified_at'), table_name='telegram_users')
    op.drop_index(op.f('ix_telegram_users_username'), table_name='telegram_users')
    op.drop_index(op.f('ix_telegram_users_outlook_profile_id'), table_name='telegram_users')
    op.drop_index(op.f('ix_telegram_users_last_seen_at'), table_name='telegram_users')
    op.drop_table('telegram_users')
    op.drop_index(op.f('ix_outlook_profiles_student_id'), table_name='outlook_profiles')
    op.drop_index(op.f('ix_outlook_profiles_graph_id'), table_name='outlook_profiles')
    op.drop_table('outlook_profiles')
