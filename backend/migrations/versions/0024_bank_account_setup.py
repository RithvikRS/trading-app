"""Immutable owner-scoped bank setup intents and historical creation receipts."""

from alembic import op

revision = "0024_bank_account_setup"
down_revision = "0023_credit_entry_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.bank_account_setups (
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            id uuid NOT NULL CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 1000),
            previous_revision bigint,
            account_id uuid NOT NULL,
            institution text NOT NULL CHECK (institution IN ('hdfc','sbi')),
            label text NOT NULL CHECK (label ~ '^[A-Za-z][A-Za-z .()-]{0,63}$'),
            currency_set text NOT NULL CHECK (currency_set IN ('INR','USD','INR,USD')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(created_at)),
            PRIMARY KEY (owner_id,id),
            UNIQUE (owner_id,revision),
            UNIQUE (owner_id,account_id),
            FOREIGN KEY (owner_id,account_id) REFERENCES app.financial_accounts(owner_id,id),
            FOREIGN KEY (owner_id,previous_revision)
                REFERENCES app.bank_account_setups(owner_id,revision)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK ((revision=1 AND previous_revision IS NULL)
                OR (revision>1 AND previous_revision IS NOT NULL AND previous_revision=revision-1))
        );
        CREATE FUNCTION app.guard_bank_setup() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $function$
        DECLARE current_revision bigint; native_currencies text;
        BEGIN
            IF TG_OP<>'INSERT' THEN
                RAISE EXCEPTION 'Bank setup receipts are immutable'; END IF;
            IF current_user='trading_runtime' THEN
                IF current_setting('transaction_isolation')<>'read committed' THEN
                    RAISE EXCEPTION 'Bank account setup is unavailable'; END IF;
                PERFORM pg_advisory_xact_lock(('x'||substr(encode(
                    sha256(convert_to('accounts/v1','UTF8')||uuid_send(NEW.owner_id)),
                    'hex'),1,16))::bit(64)::bigint);
                IF NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                    SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                    RAISE EXCEPTION 'Bank account setup is unavailable'; END IF;
                SELECT coalesce(max(revision),0) INTO current_revision
                    FROM app.bank_account_setups WHERE owner_id=NEW.owner_id;
                IF NEW.revision<>current_revision+1 OR current_revision>=1000
                    OR (SELECT count(*) FROM app.financial_accounts
                        WHERE owner_id=NEW.owner_id)>1000
                    OR NOT EXISTS (SELECT 1 FROM app.financial_accounts a
                        WHERE a.owner_id=NEW.owner_id AND a.id=NEW.account_id
                        AND a.archived_at IS NULL AND a.revision=1) THEN
                    RAISE EXCEPTION 'Bank account setup is unavailable'; END IF;
                SELECT string_agg(currency,',' ORDER BY currency) INTO native_currencies
                    FROM app.account_currencies
                    WHERE owner_id=NEW.owner_id AND account_id=NEW.account_id;
                IF NEW.currency_set IS DISTINCT FROM native_currencies THEN
                    RAISE EXCEPTION 'Bank account setup is unavailable'; END IF;
            END IF;
            RETURN NEW;
        END
        $function$;
        REVOKE ALL ON FUNCTION app.guard_bank_setup() FROM PUBLIC;
        CREATE TRIGGER guard_bank_setup BEFORE INSERT OR UPDATE OR DELETE ON app.bank_account_setups
            FOR EACH ROW EXECUTE FUNCTION app.guard_bank_setup();
        CREATE FUNCTION app.validate_bank_setup() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $function$
        BEGIN
            -- Historical declarations survive archival and later native-currency additions.
            IF NOT EXISTS (SELECT 1 FROM app.financial_accounts a
                WHERE a.owner_id=NEW.owner_id AND a.id=NEW.account_id AND a.kind='bank'
                AND a.market='IN' AND a.institution=NEW.institution AND a.label=NEW.label
                AND isfinite(a.created_at) AND NEW.created_at>=a.created_at)
                OR EXISTS (SELECT 1
                    FROM unnest(string_to_array(NEW.currency_set,',')) AS original(currency)
                    WHERE NOT EXISTS (SELECT 1 FROM app.account_currencies c
                        WHERE c.owner_id=NEW.owner_id AND c.account_id=NEW.account_id
                        AND c.currency=original.currency)) THEN
                RAISE EXCEPTION 'Bank setup declaration is inconsistent'; END IF;
            RETURN NULL;
        END
        $function$;
        REVOKE ALL ON FUNCTION app.validate_bank_setup() FROM PUBLIC;
        CREATE CONSTRAINT TRIGGER validate_bank_setup AFTER INSERT ON app.bank_account_setups
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.validate_bank_setup();
        ALTER TABLE app.bank_account_setups ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.bank_account_setups FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON app.bank_account_setups FROM PUBLIC,trading_runtime,trading_auth;
        CREATE POLICY bank_setup_owner ON app.bank_account_setups TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active));
        GRANT SELECT, INSERT
            (owner_id,id,revision,previous_revision,account_id,institution,label,currency_set)
            ON app.bank_account_setups TO trading_runtime;
    """)


def downgrade() -> None:
    op.execute("""
        DO $guard$ BEGIN
            IF EXISTS (SELECT 1 FROM app.bank_account_setups) THEN
                RAISE EXCEPTION 'Bank setup records require a forward migration'; END IF;
        END $guard$;
        DROP TABLE app.bank_account_setups;
        DROP FUNCTION app.guard_bank_setup();
        DROP FUNCTION app.validate_bank_setup();
    """)
