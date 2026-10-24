"""Immutable source observations, bounded normalization and review history."""

from alembic import op

revision = "0008_import_staging"
down_revision = "0007_instruments"
branch_labels = None
depends_on = None

TABLES = (
    "source_observations",
    "import_batches",
    "staged_rows",
    "staged_values",
    "review_decisions",
)


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app.valid_staged_value(role text, source text, amount numeric,
            currency text, missing text) RETURNS boolean
        LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE digits integer;
        BEGIN
            IF role NOT IN ('quantity','net_cash','gross_cash','unit_price','fee','withholding',
                'acquisition_cost','reported_tax_basis') OR role IS NULL THEN RETURN false;
                END IF;
            IF (role='quantity' AND currency IS NOT NULL) OR (role<>'quantity' AND
                (currency IS NULL OR currency NOT IN ('INR','USD'))) THEN RETURN false; END IF;
            IF source IS NULL THEN
                RETURN amount IS NULL AND missing IS NOT NULL AND missing IN
                    ('not_supplied','incomplete_history','unsupported','conflicting_evidence');
            END IF;
            IF amount IS NULL OR missing IS NOT NULL OR length(source)>32 OR source !~
                '^-?(0|[1-9][0-9]{0,17})([.][0-9]{1,12})?$' THEN RETURN false; END IF;
            digits := CASE WHEN role IN ('net_cash','gross_cash') THEN 2
                WHEN role IN ('quantity','unit_price') THEN 12 ELSE 8 END;
            RETURN amount<>'NaN'::numeric AND abs(amount)<1000000000000000000::numeric
                AND scale(amount)<=digits AND scale(source::numeric)<=digits
                AND source::numeric=amount AND (role<>'unit_price' OR amount>0);
        END $f$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION app.valid_staged_value(text,text,numeric,text,text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION app.valid_staged_value(text,text,numeric,text,text) TO "
        "trading_runtime"
    )
    op.execute("""
        CREATE TABLE app.source_observations (
            owner_id uuid NOT NULL,
            id uuid NOT NULL CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            source_id uuid NOT NULL,
            previous_id uuid,
            digest text NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
            digest_algorithm text NOT NULL CHECK (digest_algorithm='sha256_v1'),
            period_start date, period_end date,
            coverage text NOT NULL CHECK (coverage IN
                ('complete_activity','partial_activity','snapshot','unknown')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id), UNIQUE (owner_id,id,source_id),
            UNIQUE (owner_id,source_id,digest_algorithm,digest), UNIQUE (owner_id,previous_id),
            FOREIGN KEY (owner_id,source_id) REFERENCES app.source_accounts(owner_id,id),
            FOREIGN KEY (owner_id,previous_id,source_id)
                REFERENCES app.source_observations(owner_id,id,source_id)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK (previous_id IS NULL OR previous_id<>id),
            CHECK ((period_start IS NULL AND period_end IS NULL AND coverage='unknown') OR
                (period_start IS NOT NULL AND period_end IS NOT NULL
                    AND period_start BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'
                    AND period_end BETWEEN period_start AND DATE '9999-12-31'))
        )
    """)
    op.execute("""
        CREATE FUNCTION app.validate_observation_predecessor() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        BEGIN
            IF current_user='trading_runtime' AND NEW.previous_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM app.source_observations WHERE owner_id=NEW.owner_id
                    AND source_id=NEW.source_id AND id=NEW.previous_id) THEN
                RAISE EXCEPTION 'Observation predecessor is unavailable';
            END IF;
            RETURN NEW;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.validate_observation_predecessor() FROM PUBLIC")
    op.execute("""
        CREATE TRIGGER validate_observation_predecessor BEFORE INSERT ON app.source_observations
        FOR EACH ROW EXECUTE FUNCTION app.validate_observation_predecessor()
    """)
    op.execute("""
        CREATE TABLE app.import_batches (
            owner_id uuid NOT NULL, id uuid NOT NULL CHECK
                (id<>'00000000-0000-0000-0000-000000000000'),
            observation_id uuid NOT NULL,
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint,
            normalizer text NOT NULL CHECK (length(normalizer) BETWEEN 1 AND 48
                AND normalizer ~ '^[a-z][a-z0-9_/-]*$'),
            normalizer_version text NOT NULL CHECK (length(normalizer_version) BETWEEN 1 AND 32
                AND normalizer_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]*$'),
            normalized_digest text NOT NULL CHECK (normalized_digest ~ '^[0-9a-f]{64}$'),
            row_count integer NOT NULL CHECK (row_count BETWEEN 1 AND 100),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id), UNIQUE (owner_id,observation_id,revision),
            FOREIGN KEY (owner_id,observation_id) REFERENCES app.source_observations(owner_id,id),
            FOREIGN KEY (owner_id,observation_id,previous_revision)
                REFERENCES app.import_batches(owner_id,observation_id,revision)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK ((revision=1 AND previous_revision IS NULL) OR
                (revision>1 AND previous_revision IS NOT NULL AND previous_revision=revision-1))
        )
    """)
    op.execute("""
        CREATE TABLE app.staged_rows (
            owner_id uuid NOT NULL, id uuid NOT NULL CHECK
                (id<>'00000000-0000-0000-0000-000000000000'),
            batch_id uuid NOT NULL, occurrence integer NOT NULL CHECK (occurrence BETWEEN 1
                AND 1000000),
            kind text NOT NULL CHECK (kind IN ('cash_movement','buy','sell','subscription',
                'redemption',
                'dividend','fee','withholding','position_snapshot','cash_snapshot',
                'lot_acquisition',
                'lot_remaining','unsupported')),
            instrument_identifier_id uuid,
            trade_date date, settlement_date date, booking_date date, value_date date,
                as_of_date date,
            blocked_reason text CHECK (blocked_reason IN ('not_supplied','unsupported',
                'conflicting_evidence')),
            value_count integer NOT NULL CHECK (value_count BETWEEN 0 AND 8),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id), UNIQUE (owner_id,batch_id,occurrence),
            FOREIGN KEY (owner_id,batch_id) REFERENCES app.import_batches(owner_id,id),
            FOREIGN KEY (owner_id,instrument_identifier_id) REFERENCES
                app.instrument_identifiers(owner_id,id),
            CHECK (trade_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            CHECK (settlement_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            CHECK (booking_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            CHECK (value_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            CHECK (as_of_date BETWEEN DATE '0001-01-01' AND DATE '9999-12-31')
        )
    """)
    op.execute("""
        CREATE TABLE app.staged_values (
            owner_id uuid NOT NULL, row_id uuid NOT NULL, role text NOT NULL,
            source text, amount numeric, currency text, missing_reason text,
            PRIMARY KEY (owner_id,row_id,role),
            FOREIGN KEY (owner_id,row_id) REFERENCES app.staged_rows(owner_id,id),
            CHECK (app.valid_staged_value(role,source,amount,currency,missing_reason))
        )
    """)
    op.execute("""
        CREATE TABLE app.review_decisions (
            owner_id uuid NOT NULL, row_id uuid NOT NULL,
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint,
            action text NOT NULL CHECK (action IN ('include','exclude','reopen')),
            reason text NOT NULL,
            source_id uuid NOT NULL, account_mapping_revision bigint,
            instrument_identifier_id uuid, instrument_mapping_revision bigint,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,row_id,revision),
            FOREIGN KEY (owner_id,row_id) REFERENCES app.staged_rows(owner_id,id),
            FOREIGN KEY (owner_id,source_id) REFERENCES app.source_accounts(owner_id,id),
            FOREIGN KEY (owner_id,source_id,account_mapping_revision)
                REFERENCES app.source_account_mappings(owner_id,source_id,revision),
            FOREIGN KEY (owner_id,instrument_identifier_id,instrument_mapping_revision)
                REFERENCES app.instrument_mappings(owner_id,identifier_id,revision),
            FOREIGN KEY (owner_id,row_id,previous_revision) REFERENCES
                app.review_decisions(owner_id,row_id,revision)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK ((revision=1 AND previous_revision IS NULL) OR
                (revision>1 AND previous_revision IS NOT NULL AND previous_revision=revision-1)),
            CHECK ((action='include' AND reason='reviewed' AND account_mapping_revision IS NOT
                NULL
                    AND ((instrument_identifier_id IS NULL AND instrument_mapping_revision IS
                NULL)
                        OR (instrument_identifier_id IS NOT NULL AND
                instrument_mapping_revision IS NOT NULL)))
                OR (action='exclude' AND reason IN ('user_excluded','duplicate_suspected')
                    AND account_mapping_revision IS NULL AND instrument_mapping_revision IS NULL)
                OR (action='reopen' AND reason='reopened'
                    AND account_mapping_revision IS NULL AND instrument_mapping_revision IS NULL))
        )
    """)
    op.execute("""
        CREATE FUNCTION app.check_staged_counts() RETURNS trigger LANGUAGE plpgsql SECURITY
                INVOKER
        SET search_path=pg_catalog AS $f$
        DECLARE batch uuid; row_record record; expected integer; actual bigint;
        BEGIN
            IF TG_TABLE_NAME='import_batches' THEN batch:=NEW.id;
            ELSIF TG_TABLE_NAME='staged_rows' THEN batch:=NEW.batch_id;
            ELSE SELECT batch_id INTO batch FROM app.staged_rows WHERE owner_id=NEW.owner_id
                AND id=NEW.row_id;
            END IF;
            SELECT row_count INTO expected FROM app.import_batches WHERE owner_id=NEW.owner_id
                AND id=batch;
            SELECT count(*) INTO actual FROM app.staged_rows WHERE owner_id=NEW.owner_id AND
                batch_id=batch;
            IF expected IS NULL OR expected<>actual THEN RAISE EXCEPTION
                'Incomplete staged batch'; END IF;
            FOR row_record IN SELECT id,value_count FROM app.staged_rows WHERE
                owner_id=NEW.owner_id AND batch_id=batch LOOP
                SELECT count(*) INTO actual FROM app.staged_values WHERE owner_id=NEW.owner_id
                AND row_id=row_record.id;
                IF row_record.value_count<>actual THEN RAISE EXCEPTION
                'Incomplete staged values'; END IF;
            END LOOP;
            RETURN NULL;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.check_staged_counts() FROM PUBLIC")
    for table in ("import_batches", "staged_rows", "staged_values"):
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER check_staged_counts AFTER INSERT ON app.{table}
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_staged_counts()
        """)
    op.execute("""
        CREATE FUNCTION app.import_row_issue(own uuid, row_key uuid) RETURNS text
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE r record; quantity numeric; cash numeric;
        BEGIN
            SELECT * INTO r FROM app.staged_rows WHERE owner_id=own AND id=row_key;
            IF NOT FOUND THEN RETURN 'unavailable'; END IF;
            IF r.blocked_reason IS NOT NULL THEN RETURN r.blocked_reason; END IF;
            IF r.kind='unsupported' THEN RETURN 'unsupported'; END IF;
            IF EXISTS (SELECT 1 FROM app.staged_values WHERE owner_id=own AND row_id=row_key
                AND NOT CASE
                    WHEN r.kind IN ('cash_snapshot','fee','withholding') THEN role='net_cash'
                    WHEN r.kind='cash_movement' THEN role IN ('net_cash','fee','withholding')
                    WHEN r.kind='dividend' THEN role IN
                        ('net_cash','gross_cash','fee','withholding')
                    WHEN r.kind IN ('buy','sell','subscription','redemption') THEN role IN
                        ('quantity','net_cash','gross_cash','unit_price','fee','withholding')
                    ELSE role IN ('quantity','unit_price','acquisition_cost',
                        'reported_tax_basis','fee','withholding') END) THEN
                RETURN 'unsupported_component';
            END IF;
            SELECT amount INTO quantity FROM app.staged_values WHERE owner_id=own AND
                row_id=row_key AND role='quantity';
            SELECT amount INTO cash FROM app.staged_values WHERE owner_id=own AND
                row_id=row_key AND role='net_cash';
            IF r.kind IN ('buy','sell','subscription','redemption') THEN
                IF r.trade_date IS NULL OR quantity IS NULL OR cash IS NULL THEN RETURN
                'not_supplied'; END IF;
            ELSIF r.kind IN ('position_snapshot','lot_acquisition','lot_remaining',
                'cash_snapshot') THEN
                IF r.as_of_date IS NULL OR (r.kind='cash_snapshot' AND cash IS NULL)
                    OR (r.kind<>'cash_snapshot' AND quantity IS NULL) THEN RETURN
                'not_supplied'; END IF;
            ELSIF r.booking_date IS NULL OR cash IS NULL THEN RETURN 'not_supplied'; END IF;
            IF r.kind IN ('buy','sell','subscription','redemption','dividend',
                'position_snapshot','lot_acquisition','lot_remaining')
                AND r.instrument_identifier_id IS NULL THEN RETURN 'unresolved_instrument';
                END IF;
            IF (r.kind IN ('buy','subscription') AND (quantity<=0 OR cash>=0))
                OR (r.kind IN ('sell','redemption') AND (quantity>=0 OR cash<=0))
                OR (r.kind IN ('position_snapshot','lot_acquisition','lot_remaining',
                'cash_snapshot') AND quantity<0)
                OR (r.kind='dividend' AND cash<0) OR (r.kind IN ('fee','withholding') AND cash>0)
                THEN RETURN 'conflicting_evidence'; END IF;
            RETURN NULL;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.import_row_issue(uuid,uuid) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.import_row_issue(uuid,uuid) TO trading_runtime")
    op.execute("""
        CREATE FUNCTION app.validate_review_decision() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE r record; account uuid; security uuid; asset text; account_kind text; market text;
                fund_currency text; listing_currency text;
        BEGIN
            SELECT s.*, b.observation_id,b.revision AS batch_revision,o.source_id INTO r
                FROM app.staged_rows s JOIN app.import_batches b ON b.owner_id=s.owner_id AND
                b.id=s.batch_id
                JOIN app.source_observations o ON o.owner_id=b.owner_id AND o.id=b.observation_id
                WHERE s.owner_id=NEW.owner_id AND s.id=NEW.row_id;
            IF NOT FOUND OR r.source_id<>NEW.source_id OR r.instrument_identifier_id IS
                DISTINCT FROM NEW.instrument_identifier_id
                THEN RAISE EXCEPTION 'Review context is unavailable'; END IF;
            IF current_user='trading_runtime' AND (EXISTS (SELECT 1 FROM app.source_observations
                WHERE owner_id=NEW.owner_id AND previous_id=r.observation_id) OR EXISTS
                (SELECT 1 FROM app.import_batches
                WHERE owner_id=NEW.owner_id AND observation_id=r.observation_id AND
                revision>r.batch_revision))
                THEN RAISE EXCEPTION 'Review evidence is superseded'; END IF;
            IF NEW.action='include' THEN
                IF app.import_row_issue(NEW.owner_id,NEW.row_id) IS NOT NULL THEN RAISE
                EXCEPTION 'Review candidate is blocked'; END IF;
                SELECT m.account_id,a.kind,a.market INTO account,account_kind,market
                FROM app.source_account_mappings m JOIN
                app.financial_accounts a
                    ON a.owner_id=m.owner_id AND a.id=m.account_id WHERE m.owner_id=NEW.owner_id
                    AND m.source_id=NEW.source_id AND m.revision=NEW.account_mapping_revision
                    AND (current_user<>'trading_runtime' OR a.archived_at IS NULL);
                IF account IS NULL THEN RAISE EXCEPTION 'Review account is unavailable'; END IF;
                IF EXISTS (SELECT 1 FROM app.staged_values v WHERE v.owner_id=NEW.owner_id AND
                v.row_id=NEW.row_id
                    AND v.currency IS NOT NULL AND NOT EXISTS (SELECT 1 FROM
                app.account_currencies c
                        WHERE c.owner_id=NEW.owner_id AND c.account_id=account AND
                c.currency=v.currency))
                    THEN RAISE EXCEPTION 'Review currency is unavailable'; END IF;
                IF NEW.instrument_identifier_id IS NOT NULL THEN
                    SELECT m.instrument_id,i.asset_class,i.fund_currency,l.quote_currency
                    INTO security,asset,fund_currency,listing_currency FROM
                app.instrument_mappings m
                        JOIN app.instruments i ON i.owner_id=m.owner_id AND i.id=m.instrument_id
                        LEFT JOIN app.instrument_listings l
                            ON l.owner_id=m.owner_id AND l.id=m.listing_id
                        WHERE m.owner_id=NEW.owner_id AND
                m.identifier_id=NEW.instrument_identifier_id
                            AND m.revision=NEW.instrument_mapping_revision;
                    IF security IS NULL OR (r.kind IN ('subscription','redemption') AND
                asset<>'mutual_fund')
                        OR (r.kind IN ('buy','sell') AND asset NOT IN ('equity','etf'))
                        THEN RAISE EXCEPTION 'Review instrument is unavailable'; END IF;
                    IF account_kind='bank' OR (account_kind='mutual_fund' AND asset<>'mutual_fund')
                        OR (account_kind='employee_stock' AND asset<>'equity')
                        OR (account_kind='brokerage' AND market='US' AND asset='mutual_fund')
                        OR (listing_currency IS NOT NULL AND listing_currency<>
                            CASE WHEN market='IN' THEN 'INR' ELSE 'USD' END)
                        OR (fund_currency IS NOT NULL AND NOT EXISTS (
                            SELECT 1 FROM app.account_currencies WHERE owner_id=NEW.owner_id
                                AND account_id=account AND currency=fund_currency))
                        OR r.kind='cash_snapshot' THEN
                        RAISE EXCEPTION 'Review account and instrument are incompatible';
                    END IF;
                END IF;
                IF current_user='trading_runtime' AND (EXISTS (SELECT 1 FROM
                app.source_account_mappings
                    WHERE owner_id=NEW.owner_id AND source_id=NEW.source_id AND
                revision>NEW.account_mapping_revision)
                    OR EXISTS (SELECT 1 FROM app.instrument_mappings WHERE owner_id=NEW.owner_id
                        AND identifier_id=NEW.instrument_identifier_id AND
                revision>NEW.instrument_mapping_revision))
                    THEN RAISE EXCEPTION 'Review mapping is stale'; END IF;
            END IF;
            RETURN NEW;
        END $f$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.validate_review_decision() FROM PUBLIC")
    op.execute("""
        CREATE TRIGGER validate_review_decision BEFORE INSERT ON app.review_decisions
        FOR EACH ROW EXECUTE FUNCTION app.validate_review_decision()
    """)
    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth")
        op.execute(f"""
            CREATE POLICY import_owner ON app.{table} TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
        """)
        op.execute(f"GRANT SELECT ON app.{table} TO trading_runtime")
    columns = {
        "source_observations": (
            "owner_id,id,source_id,previous_id,digest,digest_algorithm,period_start,"
            "period_end,coverage"
        ),
        "import_batches": (
            "owner_id,id,observation_id,revision,previous_revision,normalizer,"
            "normalizer_version,normalized_digest,row_count"
        ),
        "staged_rows": (
            "owner_id,id,batch_id,occurrence,kind,instrument_identifier_id,trade_date,"
            "settlement_date,booking_date,value_date,as_of_date,blocked_reason,value_count"
        ),
        "staged_values": "owner_id,row_id,role,source,amount,currency,missing_reason",
        "review_decisions": (
            "owner_id,row_id,revision,previous_revision,action,reason,source_id,"
            "account_mapping_revision,instrument_identifier_id,instrument_mapping_revision"
        ),
    }
    for table, names in columns.items():
        op.execute(f"GRANT INSERT ({names}) ON app.{table} TO trading_runtime")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    op.execute("DROP FUNCTION app.validate_review_decision()")
    op.execute("DROP FUNCTION app.import_row_issue(uuid,uuid)")
    op.execute("DROP FUNCTION app.check_staged_counts()")
    op.execute("DROP FUNCTION app.valid_staged_value(text,text,numeric,text,text)")
    op.execute("DROP FUNCTION app.validate_observation_predecessor()")
