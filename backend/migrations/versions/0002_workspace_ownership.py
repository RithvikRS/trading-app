"""Add internal owners, closed identity mappings, and isolated display preferences."""

from alembic import op

revision = "0002_workspace_ownership"
down_revision = "0001_private_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.owners (
            id uuid PRIMARY KEY CHECK (id <> '00000000-0000-0000-0000-000000000000'::uuid),
            is_active boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp()
        )
    """)
    op.execute("""
        CREATE TABLE app.owner_identities (
            issuer text COLLATE "C" NOT NULL
                CHECK (octet_length(issuer) BETWEEN 1 AND 512 AND issuer = btrim(issuer)),
            subject text COLLATE "C" NOT NULL
                CHECK (octet_length(subject) BETWEEN 1 AND 256 AND subject = btrim(subject)),
            owner_id uuid NOT NULL REFERENCES app.owners(id) ON DELETE RESTRICT,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (issuer, subject)
        )
    """)
    op.execute("CREATE INDEX owner_identities_owner_idx ON app.owner_identities(owner_id)")
    op.execute("""
        CREATE TABLE app.workspace_preferences (
            owner_id uuid PRIMARY KEY REFERENCES app.owners(id) ON DELETE RESTRICT,
            theme text NOT NULL DEFAULT 'light' CHECK (theme IN ('light', 'dark')),
            display_currency text NOT NULL DEFAULT 'INR' CHECK (display_currency IN ('INR', 'USD')),
            amount_masked boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp()
        )
    """)
    op.execute("""
        CREATE FUNCTION app.current_owner_id() RETURNS uuid
        LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog
        AS $function$
            SELECT CASE
                WHEN length(value) = 36 AND value ~
                    '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                THEN value::uuid ELSE NULL END
            FROM (SELECT current_setting('app.owner_id', true) AS value) AS context
        $function$
    """)
    op.execute("""
        CREATE FUNCTION app.touch_workspace_preferences() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
        AS $function$
        BEGIN
            NEW.updated_at := statement_timestamp();
            RETURN NEW;
        END
        $function$
    """)
    op.execute("""
        CREATE TRIGGER workspace_preferences_updated
        BEFORE UPDATE ON app.workspace_preferences
        FOR EACH ROW EXECUTE FUNCTION app.touch_workspace_preferences()
    """)
    for table in ("owners", "owner_identities", "workspace_preferences"):
        op.execute(f"REVOKE ALL ON TABLE app.{table} FROM PUBLIC, trading_runtime")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
    # Identity mappings have no runtime grants or policies. Provisioning and future
    # authenticated lookup need their own administrative/limited access paths.
    op.execute("""
        CREATE POLICY owner_read ON app.owners FOR SELECT TO trading_runtime
        USING (id = app.current_owner_id() AND is_active)
    """)
    op.execute("""
        CREATE POLICY preferences_owner ON app.workspace_preferences TO trading_runtime
        USING (
            owner_id = app.current_owner_id()
            AND EXISTS (SELECT 1 FROM app.owners AS owner
                        WHERE owner.id = workspace_preferences.owner_id AND owner.is_active)
        )
        WITH CHECK (
            owner_id = app.current_owner_id()
            AND EXISTS (SELECT 1 FROM app.owners AS owner
                        WHERE owner.id = workspace_preferences.owner_id AND owner.is_active)
        )
    """)
    op.execute("REVOKE ALL ON FUNCTION app.current_owner_id() FROM PUBLIC")
    op.execute(
        "REVOKE ALL ON FUNCTION app.touch_workspace_preferences() FROM PUBLIC, trading_runtime"
    )
    op.execute("GRANT EXECUTE ON FUNCTION app.current_owner_id() TO trading_runtime")
    op.execute("GRANT SELECT ON app.owners, app.workspace_preferences TO trading_runtime")
    op.execute("""
        GRANT INSERT (owner_id, theme, display_currency, amount_masked),
              UPDATE (theme, display_currency, amount_masked)
        ON app.workspace_preferences TO trading_runtime
    """)


def downgrade() -> None:
    # The runner restricts downgrades to disposable clusters. No CASCADE: unexpected
    # dependencies must fail and roll back instead of being silently removed.
    op.execute("DROP TABLE app.workspace_preferences")
    op.execute("DROP TABLE app.owner_identities")
    op.execute("DROP TABLE app.owners")
    op.execute("DROP FUNCTION app.touch_workspace_preferences()")
    op.execute("DROP FUNCTION app.current_owner_id()")
