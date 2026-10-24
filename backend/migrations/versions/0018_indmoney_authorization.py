"""Private, owned connector custody and single-use authorization attempts."""

from alembic import op

revision = "0018_indmoney_authorization"
down_revision = "0017_reconciled_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.indmoney_connections (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            owner_id uuid NOT NULL UNIQUE REFERENCES app.owners(id),
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            status text NOT NULL CHECK (status IN
                ('disconnected','pending','authorized','refreshing','reconnect_required')),
            sealed bytea CHECK (octet_length(sealed) BETWEEN 33 AND 32800),
            client_binding text NOT NULL CHECK (client_binding ~ '^[0-9a-f]{64}$'),
            expires_at timestamptz,
            lease uuid,
            lease_until timestamptz,
            lease_session bytea,
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            UNIQUE(owner_id, id),
            CHECK ((sealed IS NOT NULL) = (status IN ('authorized','refreshing'))),
            CHECK ((expires_at IS NOT NULL) = (sealed IS NOT NULL)),
            CHECK ((lease IS NOT NULL) = (lease_until IS NOT NULL)),
            CHECK ((lease IS NOT NULL) = (lease_session IS NOT NULL)),
            CHECK (lease_session IS NULL OR octet_length(lease_session)=32),
            CHECK (lease IS NULL OR status IN ('pending','refreshing'))
        );
        CREATE TABLE app.indmoney_attempts (
            state_hash bytea PRIMARY KEY CHECK (octet_length(state_hash)=32),
            browser_hash bytea NOT NULL CHECK (octet_length(browser_hash)=32),
            owner_id uuid NOT NULL,
            connection_id uuid NOT NULL UNIQUE,
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            session_verifier bytea NOT NULL REFERENCES app.auth_sessions(verifier)
                ON DELETE CASCADE,
            sealed bytea NOT NULL CHECK (octet_length(sealed) BETWEEN 33 AND 32800),
            stage text NOT NULL CHECK (stage IN ('awaiting','received')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            expires_at timestamptz NOT NULL DEFAULT statement_timestamp() + interval '5 minutes',
            FOREIGN KEY(owner_id, connection_id) REFERENCES app.indmoney_connections(owner_id,id),
            CHECK (expires_at > created_at AND expires_at <= created_at + interval '5 minutes')
        );
        CREATE TABLE app.indmoney_events (
            id uuid PRIMARY KEY,
            owner_id uuid NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            event text NOT NULL CHECK (event IN
                ('start','callback','authorize','refresh','disconnect','rotate')),
            outcome text NOT NULL CHECK (outcome IN ('success','denied','unavailable')),
            request_id text NOT NULL CHECK (request_id ~ '^[0-9a-f]{32}$')
        );
        CREATE INDEX indmoney_events_admission ON app.indmoney_events(event, occurred_at);
        GRANT EXECUTE ON FUNCTION app.current_owner_id() TO trading_auth;
    """)
    for table in ("indmoney_connections", "indmoney_attempts", "indmoney_events"):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
    op.execute("""
        GRANT SELECT, INSERT ON app.indmoney_connections TO trading_auth;
        GRANT UPDATE (revision,status,sealed,client_binding,expires_at,lease,lease_until,
            lease_session,updated_at) ON app.indmoney_connections TO trading_auth;
        CREATE POLICY connector_owner ON app.indmoney_connections TO trading_auth
            USING (owner_id=app.current_owner_id() AND EXISTS
                (SELECT 1 FROM app.owners WHERE id=owner_id AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS
                (SELECT 1 FROM app.owners WHERE id=owner_id AND is_active));
        GRANT SELECT, INSERT, DELETE ON app.indmoney_attempts TO trading_auth;
        GRANT UPDATE (sealed,stage) ON app.indmoney_attempts TO trading_auth;
        CREATE POLICY callback_registry ON app.indmoney_attempts TO trading_auth
            USING (true) WITH CHECK (true);
        GRANT SELECT, INSERT ON app.indmoney_events TO trading_auth;
        CREATE POLICY connector_event_read ON app.indmoney_events FOR SELECT
            TO trading_auth USING (true);
        CREATE POLICY connector_event_append ON app.indmoney_events FOR INSERT
            TO trading_auth WITH CHECK (true);
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM app.indmoney_connections)
                OR EXISTS (SELECT 1 FROM app.indmoney_attempts)
                OR EXISTS (SELECT 1 FROM app.indmoney_events) THEN
                RAISE EXCEPTION 'Connector state requires a forward migration';
            END IF;
        END $$;
        DROP TABLE app.indmoney_attempts;
        DROP TABLE app.indmoney_connections;
        DROP TABLE app.indmoney_events;
        REVOKE EXECUTE ON FUNCTION app.current_owner_id() FROM trading_auth;
    """)
