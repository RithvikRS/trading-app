"""Owned accounts, encrypted source identities, and append-only mapping revisions."""

from alembic import op

revision = "0006_accounts_sources"
down_revision = "0005_preference_revisions"
branch_labels = None
depends_on = None

TABLES = ("financial_accounts", "account_currencies", "source_accounts", "source_account_mappings")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.financial_accounts (
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            kind text NOT NULL,
            institution text NOT NULL,
            market text NOT NULL,
            label text NOT NULL CHECK (label ~ '^[A-Za-z][A-Za-z .()-]{0,63}$'),
            archived_at timestamptz CHECK (isfinite(archived_at)),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision BETWEEN 1 AND 9007199254740991),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id, id),
            CHECK ((kind = 'bank' AND institution IN ('hdfc', 'sbi') AND market = 'IN')
                OR (kind = 'brokerage' AND institution = 'indmoney' AND market IN ('IN', 'US'))
                OR (kind = 'mutual_fund' AND institution = 'fund_registrar' AND market = 'IN')
                OR (kind = 'employee_stock' AND institution = 'ubs' AND market = 'US'))
        )
    """)
    op.execute("""
        CREATE TABLE app.account_currencies (
            owner_id uuid NOT NULL,
            account_id uuid NOT NULL,
            currency text NOT NULL CHECK (currency IN ('INR', 'USD')),
            PRIMARY KEY (owner_id, account_id, currency),
            FOREIGN KEY (owner_id, account_id) REFERENCES app.financial_accounts(owner_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE app.source_accounts (
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            namespace text NOT NULL CHECK (namespace IN ('hdfc_statement', 'sbi_statement',
                'indmoney_india', 'indmoney_us', 'indmoney_funds', 'cas', 'advisor', 'ubs_espp')),
            key_version integer NOT NULL CHECK (key_version BETWEEN 1 AND 2147483647),
            key_check text NOT NULL CHECK (key_check ~ '^[0-9a-f]{64}$'),
            fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
            encrypted_reference text NOT NULL CHECK (
                length(encrypted_reference) BETWEEN 40 AND 256
                AND encrypted_reference ~ '^[A-Za-z0-9_=-]+$'),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision BETWEEN 1 AND 9007199254740991),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id, id),
            UNIQUE (owner_id, namespace, key_version, fingerprint)
        )
    """)
    op.execute("""
        CREATE TABLE app.source_account_mappings (
            owner_id uuid NOT NULL,
            source_id uuid NOT NULL,
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint,
            account_id uuid,
            reason text NOT NULL CHECK (reason IN ('initial', 'correction', 'unlinked')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id, source_id, revision),
            FOREIGN KEY (owner_id, source_id) REFERENCES app.source_accounts(owner_id, id),
            FOREIGN KEY (owner_id, account_id) REFERENCES app.financial_accounts(owner_id, id),
            FOREIGN KEY (owner_id, source_id, previous_revision)
                REFERENCES app.source_account_mappings(owner_id, source_id, revision)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK ((revision = 1 AND previous_revision IS NULL AND reason = 'initial')
                OR (revision > 1 AND previous_revision IS NOT NULL
                    AND previous_revision = revision - 1 AND reason <> 'initial')),
            CHECK ((account_id IS NULL AND reason = 'unlinked')
                OR (account_id IS NOT NULL AND reason <> 'unlinked'))
        )
    """)
    op.execute("""
        CREATE INDEX source_account_mappings_account ON app.source_account_mappings
            (owner_id, account_id, source_id, revision)
    """)
    op.execute("""
        CREATE FUNCTION app.touch_account_record() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $function$
        BEGIN
            IF TG_TABLE_NAME = 'financial_accounts' THEN
                IF OLD.archived_at IS NOT NULL OR NEW.archived_at IS NULL THEN
                    RAISE EXCEPTION 'Account archive is final';
                END IF;
                NEW.archived_at := statement_timestamp();
            END IF;
            NEW.revision := OLD.revision + 1;
            NEW.updated_at := statement_timestamp();
            RETURN NEW;
        END
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.touch_account_record() FROM PUBLIC")
    for table in ("financial_accounts", "source_accounts"):
        op.execute(f"""
            CREATE TRIGGER touch_account_record BEFORE UPDATE ON app.{table}
            FOR EACH ROW EXECUTE FUNCTION app.touch_account_record()
        """)
    op.execute("""
        CREATE FUNCTION app.require_account_currency() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $function$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM app.account_currencies
                WHERE owner_id=NEW.owner_id AND account_id=NEW.id) THEN
                RAISE EXCEPTION 'Account requires a native currency';
            END IF;
            RETURN NULL;
        END
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.require_account_currency() FROM PUBLIC")
    op.execute("""
        CREATE CONSTRAINT TRIGGER require_account_currency AFTER INSERT ON app.financial_accounts
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.require_account_currency()
    """)
    op.execute("""
        CREATE FUNCTION app.validate_account_mapping() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog AS $function$
        DECLARE compatible boolean;
        BEGIN
            IF NEW.account_id IS NULL THEN RETURN NEW; END IF;
            SELECT CASE s.namespace
                WHEN 'hdfc_statement' THEN a.kind='bank' AND a.institution='hdfc'
                WHEN 'sbi_statement' THEN a.kind='bank' AND a.institution='sbi'
                WHEN 'indmoney_india' THEN a.kind='brokerage' AND a.market='IN'
                WHEN 'indmoney_us' THEN a.kind='brokerage' AND a.market='US'
                WHEN 'ubs_espp' THEN a.kind='employee_stock'
                ELSE a.kind='mutual_fund' END
                AND (current_user <> 'trading_runtime' OR a.archived_at IS NULL)
                INTO compatible
                FROM app.source_accounts s JOIN app.financial_accounts a
                    ON a.owner_id=s.owner_id
                WHERE s.owner_id=NEW.owner_id AND s.id=NEW.source_id AND a.id=NEW.account_id;
            IF compatible IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Account mapping is unavailable';
            END IF;
            RETURN NEW;
        END
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.validate_account_mapping() FROM PUBLIC")
    op.execute("""
        CREATE TRIGGER validate_account_mapping BEFORE INSERT ON app.source_account_mappings
        FOR EACH ROW EXECUTE FUNCTION app.validate_account_mapping()
    """)
    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC, trading_runtime, trading_auth")
        op.execute(f"""
            CREATE POLICY account_owner ON app.{table} TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active))
        """)
        op.execute(f"GRANT SELECT ON app.{table} TO trading_runtime")
    op.execute("""
        GRANT INSERT (owner_id, id, kind, institution, market, label), UPDATE (archived_at)
        ON app.financial_accounts TO trading_runtime
    """)
    op.execute("GRANT INSERT ON app.account_currencies TO trading_runtime")
    op.execute("""
        GRANT INSERT (owner_id, id, namespace, key_version, key_check,
                      fingerprint, encrypted_reference),
        UPDATE (key_version, key_check, fingerprint, encrypted_reference)
        ON app.source_accounts TO trading_runtime
    """)
    op.execute("""
        GRANT INSERT (owner_id, source_id, revision, previous_revision, account_id, reason)
        ON app.source_account_mappings TO trading_runtime
    """)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    for function in (
        "validate_account_mapping",
        "require_account_currency",
        "touch_account_record",
    ):
        op.execute(f"DROP FUNCTION app.{function}()")
