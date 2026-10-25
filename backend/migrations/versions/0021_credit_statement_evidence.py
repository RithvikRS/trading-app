"""Immutable credit statement observations and exact checkpoint values."""

from alembic import op

revision = "0021_credit_statement_evidence"
down_revision = "0020_credit_source_mappings"
branch_labels = None
depends_on = None

ROLES = ("opening_liability", "closing_liability", "total_due", "minimum_due")


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.credit_source_account_mappings ADD CONSTRAINT credit_mapping_binding
            UNIQUE (owner_id,source_id,revision,account_id);
        CREATE TABLE app.credit_evidence_observations (
            owner_id uuid NOT NULL,
            id uuid NOT NULL CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint,
            source_id uuid NOT NULL,
            mapping_revision bigint NOT NULL,
            account_id uuid NOT NULL,
            kind text NOT NULL CHECK (kind='statement'),
            contract_version integer NOT NULL CHECK (contract_version=1),
            reason text NOT NULL CHECK (reason IN ('initial','correction')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp()
                CHECK (isfinite(created_at)),
            PRIMARY KEY (owner_id,id,revision),
            UNIQUE (owner_id,id,revision,source_id,account_id,kind),
            FOREIGN KEY (owner_id,source_id,mapping_revision,account_id)
                REFERENCES app.credit_source_account_mappings
                    (owner_id,source_id,revision,account_id),
            FOREIGN KEY (owner_id,id,previous_revision,source_id,account_id,kind)
                REFERENCES app.credit_evidence_observations
                    (owner_id,id,revision,source_id,account_id,kind)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK ((revision=1 AND previous_revision IS NULL AND reason='initial') OR
                (revision>1 AND previous_revision IS NOT NULL
                    AND previous_revision=revision-1 AND reason='correction'))
        );
        CREATE INDEX credit_evidence_account ON app.credit_evidence_observations
            (owner_id,account_id,id,revision);
    """)
    values = ",\n".join(
        f"""
            {role}_source text, {role}_amount numeric, {role}_missing text,
            CHECK (app.valid_staged_value('net_cash',{role}_source,{role}_amount,
                'INR',{role}_missing))
        """
        for role in ROLES
    )
    op.execute(f"""
        CREATE TABLE app.credit_statement_values (
            owner_id uuid NOT NULL,
            observation_id uuid NOT NULL,
            revision bigint NOT NULL,
            period_start date NOT NULL CHECK (
                period_start BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            period_end date NOT NULL CHECK (
                period_end BETWEEN period_start AND DATE '9999-12-31'),
            statement_date date NOT NULL CHECK (
                statement_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            due_date date CHECK (
                due_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            {values},
            CHECK (minimum_due_amount IS NULL OR minimum_due_amount>=0),
            PRIMARY KEY (owner_id,observation_id,revision),
            FOREIGN KEY (owner_id,observation_id,revision)
                REFERENCES app.credit_evidence_observations(owner_id,id,revision)
                DEFERRABLE INITIALLY DEFERRED
        );
        ALTER TABLE app.credit_evidence_observations ADD CONSTRAINT credit_statement_required
            FOREIGN KEY (owner_id,id,revision)
                REFERENCES app.credit_statement_values(owner_id,observation_id,revision)
                DEFERRABLE INITIALLY DEFERRED;
    """)
    op.execute("""
        CREATE FUNCTION app.guard_credit_statement() RETURNS trigger
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
                        AND o.revision=NEW.revision
                        AND NOT EXISTS (SELECT 1 FROM app.credit_source_account_mappings n
                            WHERE n.owner_id=m.owner_id AND n.source_id=m.source_id
                                AND n.revision>m.revision);
                IF NOT FOUND OR target_account IS NULL THEN
                    RAISE EXCEPTION 'Credit statement operation is unavailable'; END IF;
                IF (SELECT count(*) FROM app.credit_statement_values
                    WHERE owner_id=NEW.owner_id)>=1000 THEN
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
    """)
    for table in ("credit_evidence_observations", "credit_statement_values"):
        op.execute(f"""
            CREATE TRIGGER guard_credit_statement BEFORE INSERT OR UPDATE OR DELETE
                ON app.{table} FOR EACH ROW EXECUTE FUNCTION app.guard_credit_statement();
            ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY;
            REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth;
            CREATE POLICY credit_statement_owner ON app.{table} TO trading_runtime
                USING (owner_id=app.current_owner_id() AND EXISTS (
                    SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active))
                WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (
                    SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active));
            GRANT SELECT ON app.{table} TO trading_runtime;
        """)
    columns = ",".join(f"{role}_source,{role}_amount,{role}_missing" for role in ROLES)
    op.execute(f"""
        GRANT INSERT (owner_id,id,revision,previous_revision,source_id,mapping_revision,
            account_id,kind,contract_version,reason) ON app.credit_evidence_observations
            TO trading_runtime;
        GRANT INSERT (owner_id,observation_id,revision,period_start,period_end,statement_date,
            due_date,{columns}) ON app.credit_statement_values TO trading_runtime;
    """)


def downgrade() -> None:
    op.execute("""
        DO $guard$ BEGIN
            IF EXISTS (SELECT 1 FROM app.credit_evidence_observations) OR
                EXISTS (SELECT 1 FROM app.credit_statement_values) THEN
                RAISE EXCEPTION 'Credit statement records require a forward migration'; END IF;
        END $guard$;
        ALTER TABLE app.credit_evidence_observations DROP CONSTRAINT credit_statement_required;
        DROP TABLE app.credit_statement_values;
        DROP TABLE app.credit_evidence_observations;
        DROP FUNCTION app.guard_credit_statement();
        ALTER TABLE app.credit_source_account_mappings DROP CONSTRAINT credit_mapping_binding;
    """)
