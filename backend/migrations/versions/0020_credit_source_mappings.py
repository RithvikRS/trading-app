"""Opaque credit-source handles and append-only billing-account mapping history."""

from alembic import op

revision = "0020_credit_source_mappings"
down_revision = "0019_credit_billing_accounts"
branch_labels = None
depends_on = None

TABLES = ("credit_source_handles", "credit_source_account_mappings")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.credit_source_handles (
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            family text NOT NULL CHECK (family='hdfc_credit_statement'),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(created_at)),
            PRIMARY KEY (owner_id,id)
        );
        CREATE TABLE app.credit_source_account_mappings (
            owner_id uuid NOT NULL,
            source_id uuid NOT NULL,
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint,
            account_id uuid,
            reason text NOT NULL CHECK (reason IN ('initial','correction','unlinked')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(created_at)),
            PRIMARY KEY (owner_id,source_id,revision),
            FOREIGN KEY (owner_id,source_id) REFERENCES app.credit_source_handles(owner_id,id),
            FOREIGN KEY (owner_id,account_id) REFERENCES app.credit_billing_accounts(owner_id,id),
            FOREIGN KEY (owner_id,source_id,previous_revision)
                REFERENCES app.credit_source_account_mappings(owner_id,source_id,revision)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK ((revision=1 AND previous_revision IS NULL AND reason='initial') OR
                (revision>1 AND previous_revision=revision-1 AND previous_revision IS NOT NULL
                    AND reason<>'initial')),
            CHECK ((account_id IS NULL AND reason='unlinked') OR
                (account_id IS NOT NULL AND reason<>'unlinked'))
        );
        CREATE INDEX credit_source_mapping_account ON app.credit_source_account_mappings
            (owner_id,account_id,source_id,revision);
        CREATE FUNCTION app.guard_credit_source() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $function$
        DECLARE current_revision bigint; current_account uuid; archived timestamptz;
        BEGIN
            IF current_user<>'trading_runtime' THEN RETURN NEW; END IF;
            IF current_setting('transaction_isolation')<>'read committed'
                OR NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                    SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                RAISE EXCEPTION 'Credit source operation is unavailable'; END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('credit-accounts/v1:' || NEW.owner_id::text, 0));
            IF NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                RAISE EXCEPTION 'Credit source operation is unavailable'; END IF;
            IF TG_TABLE_NAME='credit_source_handles' THEN
                IF (SELECT count(*) FROM app.credit_source_handles
                    WHERE owner_id=NEW.owner_id)>=1000 THEN
                    RAISE EXCEPTION 'Credit source operation is unavailable'; END IF;
            ELSE
                IF NOT EXISTS (SELECT 1 FROM app.credit_source_handles
                    WHERE owner_id=NEW.owner_id AND id=NEW.source_id) THEN
                    RAISE EXCEPTION 'Credit source operation is unavailable'; END IF;
                SELECT revision,account_id INTO current_revision,current_account
                    FROM app.credit_source_account_mappings
                    WHERE owner_id=NEW.owner_id AND source_id=NEW.source_id
                    ORDER BY revision DESC LIMIT 1;
                IF NEW.revision IS DISTINCT FROM coalesce(current_revision,0)+1 OR
                    NEW.previous_revision IS DISTINCT FROM current_revision OR
                    (current_revision IS NOT NULL AND
                        NEW.account_id IS NOT DISTINCT FROM current_account) THEN
                    RAISE EXCEPTION 'Credit source operation is unavailable'; END IF;
                IF NEW.account_id IS NOT NULL THEN
                    SELECT archived_at INTO archived FROM app.credit_billing_accounts
                        WHERE owner_id=NEW.owner_id AND id=NEW.account_id FOR UPDATE;
                    IF NOT FOUND OR archived IS NOT NULL THEN
                        RAISE EXCEPTION 'Credit source operation is unavailable'; END IF;
                END IF;
                IF (SELECT count(*) FROM app.credit_source_account_mappings
                    WHERE owner_id=NEW.owner_id)>=1000 THEN
                    RAISE EXCEPTION 'Credit source operation is unavailable'; END IF;
            END IF;
            -- Recheck after a mapping target-row wait, not against outer INSERT/RLS state.
            IF NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                RAISE EXCEPTION 'Credit source operation is unavailable'; END IF;
            RETURN NEW;
        END
        $function$;
        REVOKE ALL ON FUNCTION app.guard_credit_source() FROM PUBLIC;
    """)
    for table in TABLES:
        op.execute(f"""
            CREATE TRIGGER guard_credit_source BEFORE INSERT ON app.{table}
                FOR EACH ROW EXECUTE FUNCTION app.guard_credit_source();
            ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY;
            REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth;
            CREATE POLICY credit_source_owner ON app.{table} TO trading_runtime
                USING (owner_id=app.current_owner_id() AND EXISTS (
                    SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active))
                WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (
                    SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active));
            GRANT SELECT ON app.{table} TO trading_runtime;
        """)
    op.execute("""
        GRANT INSERT (owner_id,id,family) ON app.credit_source_handles TO trading_runtime;
        GRANT INSERT (owner_id,source_id,revision,previous_revision,account_id,reason)
            ON app.credit_source_account_mappings TO trading_runtime;
    """)


def downgrade() -> None:
    op.execute("""
        DO $guard$ BEGIN
            IF EXISTS (SELECT 1 FROM app.credit_source_handles) OR
                EXISTS (SELECT 1 FROM app.credit_source_account_mappings) THEN
                RAISE EXCEPTION 'Credit source records require a forward migration'; END IF;
        END $guard$;
        DROP TABLE app.credit_source_account_mappings;
        DROP TABLE app.credit_source_handles;
        DROP FUNCTION app.guard_credit_source();
    """)
