"""Private authentication state, durable admission, and append-only security events."""

from alembic import op

revision = "0004_browser_sessions"
down_revision = "0003_auth_identity_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.auth_sessions (
            verifier bytea PRIMARY KEY CHECK (octet_length(verifier)=32),
            reference uuid NOT NULL UNIQUE,
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            issuer text NOT NULL,
            subject text NOT NULL,
            stage text NOT NULL CHECK
                (stage IN ('login', 'active', 'recovery', 'password', 'factor')),
            sealed bytea NOT NULL CHECK (octet_length(sealed) BETWEEN 29 AND 32768),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            idle_until timestamptz NOT NULL,
            lease uuid,
            lease_until timestamptz,
            FOREIGN KEY (issuer, subject) REFERENCES app.owner_identities(issuer, subject),
            CHECK (expires_at > created_at AND expires_at <= created_at + interval '8 hours'),
            CHECK ((lease IS NULL) = (lease_until IS NULL))
        )
    """)
    op.execute("CREATE INDEX auth_sessions_owner ON app.auth_sessions(owner_id)")
    op.execute("""
        CREATE TABLE app.auth_revocations (
            owner_id uuid PRIMARY KEY REFERENCES app.owners(id),
            revoked_before timestamptz NOT NULL DEFAULT clock_timestamp()
        )
    """)
    op.execute("""
        CREATE TABLE app.auth_admissions (
            key bytea NOT NULL CHECK (octet_length(key)=32),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
    """)
    op.execute("CREATE INDEX auth_admissions_time ON app.auth_admissions(created_at)")
    op.execute("""
        CREATE TABLE app.security_events (
            id uuid PRIMARY KEY,
            occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            event text NOT NULL CHECK (event IN (
                'login', 'mfa', 'renewal', 'logout', 'revoke_all', 'recovery_request',
                'recovery_verify', 'password_change', 'factor_add', 'factor_remove', 'expiry'
            )),
            outcome text NOT NULL CHECK (outcome IN ('success', 'denied', 'unavailable')),
            request_id text NOT NULL CHECK (request_id ~ '^[0-9a-f]{32}$'),
            actor uuid,
            session_reference uuid
        )
    """)
    op.execute("CREATE INDEX security_events_time ON app.security_events(occurred_at)")
    for name in ("auth_sessions", "auth_revocations", "auth_admissions", "security_events"):
        op.execute(f"ALTER TABLE app.{name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{name} FORCE ROW LEVEL SECURITY")
        if name == "security_events":
            op.execute(f"GRANT SELECT, INSERT ON app.{name} TO trading_auth")
            op.execute(
                f"CREATE POLICY security_read ON app.{name} FOR SELECT TO trading_auth USING (true)"
            )
            op.execute(
                f"CREATE POLICY security_append ON app.{name} FOR INSERT "
                "TO trading_auth WITH CHECK (true)"
            )
        else:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON app.{name} TO trading_auth")
            op.execute(
                f"CREATE POLICY session_registry ON app.{name} TO trading_auth "
                "USING (true) WITH CHECK (true)"
            )


def downgrade() -> None:
    # Only the guarded disposable runner supports downgrades. Session loss is intentional.
    for name in ("security_events", "auth_admissions", "auth_revocations", "auth_sessions"):
        op.execute(f"DROP TABLE app.{name}")
