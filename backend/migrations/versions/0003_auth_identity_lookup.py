"""Add a separate identity lookup role and monotonic initial-MFA marker."""

from alembic import op

revision = "0003_auth_identity_lookup"
down_revision = "0002_workspace_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE app.owner_identities ADD COLUMN mfa_enrolled boolean NOT NULL DEFAULT false"
    )
    op.execute("GRANT USAGE ON SCHEMA app TO trading_auth")
    op.execute("GRANT SELECT (id, is_active) ON app.owners TO trading_auth")
    op.execute(
        "GRANT SELECT (issuer, subject, owner_id, mfa_enrolled), UPDATE (mfa_enrolled) "
        "ON app.owner_identities TO trading_auth"
    )
    op.execute(
        "CREATE POLICY auth_owner_lookup ON app.owners FOR SELECT TO trading_auth USING (is_active)"
    )
    op.execute("""
        CREATE POLICY auth_identity_lookup ON app.owner_identities FOR SELECT TO trading_auth
        USING (EXISTS (SELECT 1 FROM app.owners WHERE id=owner_id AND is_active))
    """)
    op.execute("""
        CREATE POLICY auth_mfa_completed ON app.owner_identities FOR UPDATE TO trading_auth
        USING (EXISTS (SELECT 1 FROM app.owners WHERE id=owner_id AND is_active))
        WITH CHECK (mfa_enrolled AND EXISTS
            (SELECT 1 FROM app.owners WHERE id=owner_id AND is_active))
    """)


def downgrade() -> None:
    op.execute("DROP POLICY auth_mfa_completed ON app.owner_identities")
    op.execute("DROP POLICY auth_identity_lookup ON app.owner_identities")
    op.execute("DROP POLICY auth_owner_lookup ON app.owners")
    op.execute(
        "REVOKE SELECT (issuer, subject, owner_id, mfa_enrolled), UPDATE (mfa_enrolled) "
        "ON app.owner_identities FROM trading_auth"
    )
    op.execute("REVOKE SELECT (id, is_active) ON app.owners FROM trading_auth")
    op.execute("REVOKE USAGE ON SCHEMA app FROM trading_auth")
    op.execute("ALTER TABLE app.owner_identities DROP COLUMN mfa_enrolled")
