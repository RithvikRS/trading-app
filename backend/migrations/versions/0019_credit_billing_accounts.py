"""Owned credit billing identities with no card references or financial balances."""

from alembic import op

revision = "0019_credit_billing_accounts"
down_revision = "0018_indmoney_authorization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.credit_billing_accounts (
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            issuer text NOT NULL CHECK (issuer='hdfc'),
            billing_currency text NOT NULL CHECK (billing_currency='INR'),
            label text NOT NULL CHECK (label ~ '^[A-Za-z][A-Za-z .()-]{0,63}$'),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision IN (1,2)),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(created_at)),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(updated_at)),
            archived_at timestamptz CHECK (isfinite(archived_at)),
            PRIMARY KEY (owner_id,id),
            CHECK ((archived_at IS NULL AND revision=1 AND updated_at=created_at)
                OR (archived_at IS NOT NULL AND revision=2 AND archived_at=updated_at
                    AND updated_at>=created_at))
        );
        CREATE FUNCTION app.guard_credit_account() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $function$
        BEGIN
            -- UPDATE reaches this trigger after any target-row lock wait.
            IF current_user='trading_runtime' AND (
                current_setting('transaction_isolation')<>'read committed'
                OR NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                    SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active)) THEN
                RAISE EXCEPTION 'Credit account operation is unavailable';
            END IF;
            IF TG_OP='INSERT' THEN
                IF current_user='trading_runtime' THEN
                    PERFORM pg_advisory_xact_lock(
                        hashtextextended('credit-accounts/v1:' || NEW.owner_id::text, 0));
                    -- The outer INSERT/RLS snapshot predates a possible lock wait.
                    IF NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                        SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                        RAISE EXCEPTION 'Credit account operation is unavailable'; END IF;
                    IF (SELECT count(*) FROM app.credit_billing_accounts
                        WHERE owner_id=NEW.owner_id)>=1000 THEN
                        RAISE EXCEPTION 'Credit account operation is unavailable'; END IF;
                END IF;
                RETURN NEW;
            END IF;
            IF (NEW.owner_id,NEW.id,NEW.issuer,NEW.billing_currency,NEW.label,NEW.revision,
                NEW.created_at,NEW.updated_at) IS DISTINCT FROM
                (OLD.owner_id,OLD.id,OLD.issuer,OLD.billing_currency,OLD.label,OLD.revision,
                OLD.created_at,OLD.updated_at)
                OR OLD.archived_at IS NOT NULL OR NEW.archived_at IS NULL
                OR NEW.archived_at IS DISTINCT FROM statement_timestamp() THEN
                RAISE EXCEPTION 'Credit account operation is unavailable';
            END IF;
            NEW.revision=OLD.revision+1;
            NEW.updated_at=statement_timestamp();
            RETURN NEW;
        END
        $function$;
        REVOKE ALL ON FUNCTION app.guard_credit_account() FROM PUBLIC;
        CREATE TRIGGER guard_credit_account BEFORE INSERT OR UPDATE
            ON app.credit_billing_accounts FOR EACH ROW EXECUTE FUNCTION app.guard_credit_account();
        ALTER TABLE app.credit_billing_accounts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.credit_billing_accounts FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON app.credit_billing_accounts FROM PUBLIC,trading_runtime,trading_auth;
        CREATE POLICY credit_account_owner ON app.credit_billing_accounts TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active));
        GRANT SELECT, INSERT (owner_id,id,issuer,billing_currency,label), UPDATE (archived_at)
            ON app.credit_billing_accounts TO trading_runtime;
    """)


def downgrade() -> None:
    op.execute("""
        DO $guard$ BEGIN
            IF EXISTS (SELECT 1 FROM app.credit_billing_accounts) THEN
                RAISE EXCEPTION 'Credit account records require a forward migration'; END IF;
        END $guard$;
        DROP TABLE app.credit_billing_accounts;
        DROP FUNCTION app.guard_credit_account();
    """)
