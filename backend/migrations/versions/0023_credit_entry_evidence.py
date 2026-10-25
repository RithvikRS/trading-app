"""Immutable typed credit entry values with independent native evidence."""

from alembic import op

revision = "0023_credit_entry_evidence"
down_revision = "0022_credit_current_evidence"
branch_labels = None
depends_on = None

# Preserve the exact prior guard for empty downgrade, without importing old migrations.
PRIOR_GUARD = """
        CREATE OR REPLACE FUNCTION app.guard_credit_statement() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $function$
        DECLARE target_account uuid; archived timestamptz; latest bigint;
        BEGIN
            IF TG_OP<>'INSERT' THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            IF current_user<>'trading_runtime' THEN RETURN NEW; END IF;
            IF current_setting('transaction_isolation')<>'read committed'
                OR NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                    SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('credit-accounts/v1:' || NEW.owner_id::text,0));
            IF NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            IF TG_TABLE_NAME='credit_evidence_observations' THEN
                SELECT account_id INTO target_account FROM app.credit_source_account_mappings m
                    WHERE owner_id=NEW.owner_id AND source_id=NEW.source_id
                        AND revision=NEW.mapping_revision AND account_id=NEW.account_id
                        AND NOT EXISTS (SELECT 1 FROM app.credit_source_account_mappings n
                            WHERE n.owner_id=m.owner_id AND n.source_id=m.source_id
                                AND n.revision>m.revision);
                IF NOT FOUND OR target_account IS NULL THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
                SELECT max(revision) INTO latest FROM app.credit_evidence_observations
                    WHERE owner_id=NEW.owner_id AND id=NEW.id;
                IF NEW.revision IS DISTINCT FROM coalesce(latest,0)+1 OR
                    NEW.previous_revision IS DISTINCT FROM latest THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
                IF (SELECT count(*) FROM app.credit_evidence_observations
                    WHERE owner_id=NEW.owner_id)>=1000 THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            ELSE
                SELECT o.account_id INTO target_account FROM app.credit_evidence_observations o
                    JOIN app.credit_source_account_mappings m
                    ON m.owner_id=o.owner_id AND m.source_id=o.source_id
                        AND m.revision=o.mapping_revision AND m.account_id=o.account_id
                    WHERE o.owner_id=NEW.owner_id AND o.id=NEW.observation_id
                        AND o.revision=NEW.revision AND o.kind=CASE
                            WHEN TG_TABLE_NAME='credit_statement_values' THEN 'statement'
                            ELSE 'current' END
                        AND NOT EXISTS (SELECT 1 FROM app.credit_source_account_mappings n
                            WHERE n.owner_id=m.owner_id AND n.source_id=m.source_id
                                AND n.revision>m.revision);
                IF NOT FOUND OR target_account IS NULL THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
                IF (TG_TABLE_NAME='credit_statement_values' AND
                    (SELECT count(*) FROM app.credit_statement_values
                        WHERE owner_id=NEW.owner_id)>=1000) OR
                    (TG_TABLE_NAME='credit_current_values' AND
                    (SELECT count(*) FROM app.credit_current_values
                        WHERE owner_id=NEW.owner_id)>=1000) THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            END IF;
            SELECT archived_at INTO archived FROM app.credit_billing_accounts
                WHERE owner_id=NEW.owner_id AND id=target_account FOR UPDATE;
            IF NOT FOUND OR archived IS NOT NULL THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            IF NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            RETURN NEW;
        END
        $function$;
        REVOKE ALL ON FUNCTION app.guard_credit_statement() FROM PUBLIC;
    """

ENTRY_GUARD = """
        CREATE OR REPLACE FUNCTION app.guard_credit_statement() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $function$
        DECLARE target_account uuid; archived timestamptz; latest bigint;
        BEGIN
            IF TG_OP<>'INSERT' THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            IF current_user<>'trading_runtime' THEN RETURN NEW; END IF;
            IF current_setting('transaction_isolation')<>'read committed'
                OR NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                    SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            PERFORM pg_advisory_xact_lock(
                hashtextextended('credit-accounts/v1:' || NEW.owner_id::text,0));
            IF NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            IF TG_TABLE_NAME='credit_evidence_observations' THEN
                SELECT account_id INTO target_account FROM app.credit_source_account_mappings m
                    WHERE owner_id=NEW.owner_id AND source_id=NEW.source_id
                        AND revision=NEW.mapping_revision AND account_id=NEW.account_id
                        AND NOT EXISTS (SELECT 1 FROM app.credit_source_account_mappings n
                            WHERE n.owner_id=m.owner_id AND n.source_id=m.source_id
                                AND n.revision>m.revision);
                IF NOT FOUND OR target_account IS NULL THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
                SELECT max(revision) INTO latest FROM app.credit_evidence_observations
                    WHERE owner_id=NEW.owner_id AND id=NEW.id;
                IF NEW.revision IS DISTINCT FROM coalesce(latest,0)+1 OR
                    NEW.previous_revision IS DISTINCT FROM latest THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
                IF (SELECT count(*) FROM app.credit_evidence_observations
                    WHERE owner_id=NEW.owner_id)>=1000 THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            ELSE
                SELECT o.account_id INTO target_account FROM app.credit_evidence_observations o
                    JOIN app.credit_source_account_mappings m
                    ON m.owner_id=o.owner_id AND m.source_id=o.source_id
                        AND m.revision=o.mapping_revision AND m.account_id=o.account_id
                    WHERE o.owner_id=NEW.owner_id AND o.id=NEW.observation_id
                        AND o.revision=NEW.revision AND o.kind=CASE
                            WHEN TG_TABLE_NAME='credit_statement_values' THEN 'statement'
                            WHEN TG_TABLE_NAME='credit_current_values' THEN 'current'
                            WHEN TG_TABLE_NAME='credit_entry_values' THEN 'entry'
                            ELSE NULL END
                        AND NOT EXISTS (SELECT 1 FROM app.credit_source_account_mappings n
                            WHERE n.owner_id=m.owner_id AND n.source_id=m.source_id
                                AND n.revision>m.revision);
                IF NOT FOUND OR target_account IS NULL THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
                IF (TG_TABLE_NAME='credit_statement_values' AND
                    (SELECT count(*) FROM app.credit_statement_values
                        WHERE owner_id=NEW.owner_id)>=1000) OR
                    (TG_TABLE_NAME='credit_current_values' AND
                    (SELECT count(*) FROM app.credit_current_values
                        WHERE owner_id=NEW.owner_id)>=1000) OR
                    (TG_TABLE_NAME='credit_entry_values' AND
                    (SELECT count(*) FROM app.credit_entry_values
                        WHERE owner_id=NEW.owner_id)>=1000) THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            END IF;
            SELECT archived_at INTO archived FROM app.credit_billing_accounts
                WHERE owner_id=NEW.owner_id AND id=target_account FOR UPDATE;
            IF NOT FOUND OR archived IS NOT NULL THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            IF NEW.owner_id IS DISTINCT FROM app.current_owner_id() OR NOT EXISTS (
                SELECT 1 FROM app.owners WHERE id=NEW.owner_id AND is_active) THEN
                RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
            RETURN NEW;
        END
        $function$;
        REVOKE ALL ON FUNCTION app.guard_credit_statement() FROM PUBLIC;
    """


def upgrade() -> None:
    op.execute("""
        LOCK TABLE app.credit_evidence_observations,app.credit_statement_values,
            app.credit_current_values IN ACCESS EXCLUSIVE MODE;
        ALTER TABLE app.credit_evidence_observations
            ADD COLUMN entry_child_kind text,
            DROP CONSTRAINT credit_evidence_observations_kind_check,
            ADD CONSTRAINT credit_evidence_observations_kind_check
                CHECK (kind IN ('statement','current','entry')),
            DROP CONSTRAINT credit_evidence_child_kind,
            ADD CONSTRAINT credit_evidence_child_kind CHECK (
                (kind='statement' AND statement_child_kind IS NOT DISTINCT FROM 'statement'
                    AND current_child_kind IS NULL AND entry_child_kind IS NULL) OR
                (kind='current' AND current_child_kind IS NOT DISTINCT FROM 'current'
                    AND statement_child_kind IS NULL AND entry_child_kind IS NULL) OR
                (kind='entry' AND entry_child_kind IS NOT DISTINCT FROM 'entry'
                    AND statement_child_kind IS NULL AND current_child_kind IS NULL));
        CREATE TABLE app.credit_entry_values (
            owner_id uuid NOT NULL,
            observation_id uuid NOT NULL,
            revision bigint NOT NULL,
            kind text NOT NULL DEFAULT 'entry' CHECK (kind='entry'),
            role text NOT NULL CHECK (role IN ('posted_debit','posted_credit',
                'pending_debit','pending_credit','unresolved')),
            treatment text NOT NULL CHECK (treatment IN ('movement','ambiguous','unsupported')),
            transaction_date date CHECK (
                transaction_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            posting_date date CHECK (
                posting_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            billing_source text, billing_amount numeric, billing_missing text,
            original_source text, original_amount numeric, original_missing text,
            original_currency text,
            CHECK (app.valid_staged_value('net_cash',billing_source,billing_amount,
                'INR',billing_missing)),
            CHECK (billing_amount IS NULL OR billing_amount>=0),
            CHECK (coalesce(
                (original_currency IS NULL AND original_source IS NULL
                    AND original_amount IS NULL AND original_missing IS NULL) OR
                (original_currency IN ('INR','USD') AND
                    app.valid_staged_value('net_cash',original_source,original_amount,
                        original_currency,original_missing)
                    AND (original_amount IS NULL OR original_amount>=0)),false)),
            CHECK (role<>'unresolved' OR treatment<>'movement'),
            CHECK (role NOT IN ('pending_debit','pending_credit') OR posting_date IS NULL),
            PRIMARY KEY (owner_id,observation_id,revision),
            CONSTRAINT credit_entry_kind_key
                UNIQUE (owner_id,observation_id,revision,kind),
            CONSTRAINT credit_entry_parent_kind
                FOREIGN KEY (owner_id,observation_id,revision,kind)
                REFERENCES app.credit_evidence_observations(owner_id,id,revision,kind)
                DEFERRABLE INITIALLY DEFERRED
        );
        ALTER TABLE app.credit_evidence_observations ADD CONSTRAINT credit_entry_required
            FOREIGN KEY (owner_id,id,revision,entry_child_kind)
            REFERENCES app.credit_entry_values(owner_id,observation_id,revision,kind)
            MATCH SIMPLE DEFERRABLE INITIALLY DEFERRED;
    """)
    op.execute(ENTRY_GUARD)
    op.execute("""
        CREATE TRIGGER guard_credit_statement BEFORE INSERT OR UPDATE OR DELETE
            ON app.credit_entry_values FOR EACH ROW EXECUTE FUNCTION app.guard_credit_statement();
        ALTER TABLE app.credit_entry_values ENABLE ROW LEVEL SECURITY;
        ALTER TABLE app.credit_entry_values FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON app.credit_entry_values FROM PUBLIC,trading_runtime,trading_auth;
        CREATE POLICY credit_statement_owner ON app.credit_entry_values TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active));
        GRANT SELECT ON app.credit_entry_values TO trading_runtime;
        GRANT INSERT (entry_child_kind) ON app.credit_evidence_observations TO trading_runtime;
        GRANT INSERT (owner_id,observation_id,revision,role,treatment,transaction_date,posting_date,
            billing_source,billing_amount,billing_missing,
            original_source,original_amount,original_missing,original_currency)
            ON app.credit_entry_values TO trading_runtime;
    """)


def downgrade() -> None:
    op.execute("""
        DO $guard$ BEGIN
            IF EXISTS (SELECT 1 FROM app.credit_evidence_observations) OR
                EXISTS (SELECT 1 FROM app.credit_statement_values) OR
                EXISTS (SELECT 1 FROM app.credit_current_values) OR
                EXISTS (SELECT 1 FROM app.credit_entry_values) THEN
                RAISE EXCEPTION 'Credit entry records require a forward migration'; END IF;
        END $guard$;
        ALTER TABLE app.credit_evidence_observations DROP CONSTRAINT credit_entry_required;
        DROP TABLE app.credit_entry_values;
        ALTER TABLE app.credit_evidence_observations
            DROP CONSTRAINT credit_evidence_child_kind,
            DROP COLUMN entry_child_kind,
            DROP CONSTRAINT credit_evidence_observations_kind_check,
            ADD CONSTRAINT credit_evidence_observations_kind_check
                CHECK (kind IN ('statement','current')),
            ADD CONSTRAINT credit_evidence_child_kind CHECK (
                (kind='statement' AND statement_child_kind IS NOT DISTINCT FROM 'statement'
                    AND current_child_kind IS NULL) OR
                (kind='current' AND current_child_kind IS NOT DISTINCT FROM 'current'
                    AND statement_child_kind IS NULL));
    """)
    op.execute(PRIOR_GUARD)
