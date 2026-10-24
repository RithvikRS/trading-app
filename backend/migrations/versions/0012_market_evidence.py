"""Owned quote/NAV/FX observations, explicit corrections and source selection."""

from alembic import op

revision = "0012_market_evidence"
down_revision = "0011_snapshots"
branch_labels = None
depends_on = None

TABLES = ("market_observations", "market_selections")
TARGET = "kind,instrument_id,listing_id,currency,base_currency,quote_currency,basis"
TARGET_COLUMNS = """
    kind text NOT NULL, instrument_id uuid, listing_id uuid, currency text,
    base_currency text, quote_currency text, basis text NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES app.owners(id),
    FOREIGN KEY (owner_id,instrument_id) REFERENCES app.instruments(owner_id,id),
    FOREIGN KEY (owner_id,listing_id) REFERENCES app.instrument_listings(owner_id,id),
    CHECK (app.valid_market_target(kind,instrument_id,listing_id,currency,
        base_currency,quote_currency,basis))
"""


def upgrade() -> None:
    _contracts()
    op.execute(f"""
        CREATE TABLE app.market_observations (
            owner_id uuid NOT NULL, id uuid NOT NULL CHECK
                (id<>'00000000-0000-0000-0000-000000000000'),
            previous_id uuid, {TARGET_COLUMNS},
            adjustment text,
            namespace text NOT NULL CHECK (namespace IN
                ('manual_evidence','amfi_nav_report','exchange_quote_report','fx_rate_report')),
            digest_algorithm text NOT NULL CHECK (digest_algorithm='sha256'),
            digest text NOT NULL CHECK (length(digest)=64 AND digest ~ '^[0-9a-f]{{64}}$'),
            occurrence integer NOT NULL CHECK (occurrence BETWEEN 1 AND 1000),
            normalizer text NOT NULL CHECK (length(normalizer) BETWEEN 1 AND 48 AND
                normalizer ~ '^[a-z][a-z0-9_]{{0,47}}$'),
            normalizer_version bigint NOT NULL CHECK
                (normalizer_version BETWEEN 1 AND 9007199254740991),
            contract_version smallint NOT NULL CHECK (contract_version=1),
            observed_on date NOT NULL CHECK
                (observed_on BETWEEN DATE '0001-01-01' AND DATE '9999-12-31'),
            observed_at text, source text, amount numeric, missing_reason text,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id), UNIQUE (owner_id,previous_id),
            UNIQUE (owner_id,namespace,digest_algorithm,digest,occurrence,normalizer,
                normalizer_version),
            FOREIGN KEY (owner_id,previous_id) REFERENCES app.market_observations(owner_id,id)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK (previous_id IS NULL OR previous_id<>id),
            CHECK ((kind='quote' AND adjustment IS NOT NULL AND adjustment IN
                ('unadjusted','split_adjusted','unknown')) OR
                (kind<>'quote' AND adjustment IS NULL)),
            CHECK (namespace='manual_evidence' OR (kind='quote' AND
                namespace='exchange_quote_report') OR (kind='nav' AND namespace='amfi_nav_report')
                OR (kind='fx' AND namespace='fx_rate_report')),
            CHECK (app.valid_snapshot_instant(observed_at,observed_on)),
            CHECK (app.valid_market_amount(source,amount,missing_reason))
        )
    """)
    op.execute(f"""
        CREATE TABLE app.market_selections (
            owner_id uuid NOT NULL, id uuid NOT NULL CHECK
                (id<>'00000000-0000-0000-0000-000000000000'),
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint, {TARGET_COLUMNS}, observation_id uuid,
            reason text NOT NULL CHECK (reason IN ('reviewed','replacement','correction','clear')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id,revision),
            UNIQUE NULLS NOT DISTINCT (owner_id,{TARGET},revision),
            FOREIGN KEY (owner_id,id,previous_revision) REFERENCES
                app.market_selections(owner_id,id,revision) DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (owner_id,observation_id) REFERENCES app.market_observations(owner_id,id)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK ((revision=1 AND previous_revision IS NULL AND reason='reviewed') OR
                (revision>1 AND previous_revision IS NOT NULL AND previous_revision=revision-1
                AND reason<>'reviewed')),
            CHECK ((observation_id IS NULL AND reason='clear') OR
                (observation_id IS NOT NULL AND reason<>'clear'))
        )
    """)
    op.execute(f"CREATE INDEX market_target ON app.market_observations(owner_id,{TARGET},id)")
    _integrity()
    _privileges()


def _contracts() -> None:
    op.execute("""
        CREATE FUNCTION app.valid_market_target(kind text,instrument_id uuid,listing_id uuid,
            currency text,base_currency text,quote_currency text,basis text) RETURNS boolean
        LANGUAGE sql IMMUTABLE SECURITY INVOKER SET search_path=pg_catalog AS $f$
        SELECT coalesce((kind='fx' AND instrument_id IS NULL AND listing_id IS NULL AND
            currency IS NULL AND base_currency IN ('INR','USD') AND quote_currency IN
            ('INR','USD') AND base_currency<>quote_currency AND basis IN ('reference','spot')) OR
            (kind IN ('quote','nav') AND instrument_id IS NOT NULL AND
            instrument_id<>'00000000-0000-0000-0000-000000000000' AND
            base_currency IS NULL AND quote_currency IS NULL AND currency IN ('INR','USD') AND
            ((kind='quote' AND listing_id IS NOT NULL AND
                listing_id<>'00000000-0000-0000-0000-000000000000' AND basis IN ('close','last')) OR
            (kind='nav' AND listing_id IS NULL AND currency='INR' AND basis='nav'))),false)
        $f$
    """)
    op.execute("""
        CREATE FUNCTION app.valid_market_amount(source text,amount numeric,missing_reason text)
            RETURNS boolean LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER
            SET search_path=pg_catalog AS $f$
        BEGIN
            IF source IS NULL THEN RETURN amount IS NULL AND missing_reason IS NOT NULL AND
                missing_reason IN ('not_supplied','incomplete_history','unsupported',
                    'conflicting_evidence'); END IF;
            IF length(source)>32 OR source !~
                '^-?(0|[1-9][0-9]{0,17})([.][0-9]{1,12})?$' THEN RETURN false; END IF;
            RETURN amount IS NOT NULL AND missing_reason IS NULL AND amount=source::numeric
                AND abs(amount)<1000000000000000000;
        END $f$
    """)
    for signature in (
        "valid_market_target(text,uuid,uuid,text,text,text,text)",
        "valid_market_amount(text,numeric,text)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO trading_runtime")


def _integrity() -> None:
    op.execute("""
        CREATE FUNCTION app.check_market_identity() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        BEGIN
            IF (NEW.kind='nav' AND NOT EXISTS (SELECT 1 FROM app.instruments i WHERE
                i.owner_id=NEW.owner_id AND i.id=NEW.instrument_id AND i.asset_class='mutual_fund'
                AND i.fund_currency=NEW.currency)) OR
                (NEW.kind='quote' AND NOT EXISTS (SELECT 1 FROM app.instrument_listings l JOIN
                app.instruments i ON i.owner_id=l.owner_id AND i.id=l.instrument_id WHERE
                l.owner_id=NEW.owner_id AND l.id=NEW.listing_id AND i.id=NEW.instrument_id AND
                i.asset_class IN ('equity','etf') AND l.quote_currency=NEW.currency)) THEN
                RAISE EXCEPTION 'Market identity is inconsistent'; END IF;
            RETURN NULL;
        END $f$
    """)
    same_target = "(" + ",".join("NEW." + key for key in TARGET.split(",")) + ")"
    prior_target = "(" + ",".join("prior." + key for key in TARGET.split(",")) + ")"
    op.execute(f"""
        CREATE FUNCTION app.check_market_observation() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE prior record;
        BEGIN
            IF NEW.previous_id IS NOT NULL THEN
                SELECT * INTO prior FROM app.market_observations WHERE owner_id=NEW.owner_id
                    AND id=NEW.previous_id;
                IF NOT FOUND OR {same_target} IS DISTINCT FROM {prior_target} THEN
                    RAISE EXCEPTION 'Market correction identity is inconsistent'; END IF;
                IF EXISTS (WITH RECURSIVE ancestors(id,previous_id) AS (
                    SELECT id,previous_id FROM app.market_observations WHERE owner_id=NEW.owner_id
                        AND id=NEW.previous_id
                    UNION SELECT p.id,p.previous_id FROM app.market_observations p JOIN ancestors a
                        ON p.id=a.previous_id WHERE p.owner_id=NEW.owner_id)
                    SELECT 1 FROM ancestors WHERE id=NEW.id) THEN
                    RAISE EXCEPTION 'Market correction history is cyclic'; END IF;
            END IF;
            RETURN NULL;
        END $f$
    """)
    selected_target = "(" + ",".join("chosen." + key for key in TARGET.split(",")) + ")"
    op.execute(f"""
        CREATE FUNCTION app.check_market_selection() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE prior app.market_selections%ROWTYPE; chosen app.market_observations%ROWTYPE;
        BEGIN
            IF NEW.revision>1 THEN
                SELECT * INTO prior FROM app.market_selections WHERE owner_id=NEW.owner_id
                    AND id=NEW.id AND revision=NEW.previous_revision;
                IF NOT FOUND OR {same_target} IS DISTINCT FROM {prior_target} THEN
                    RAISE EXCEPTION 'Market selection history is inconsistent'; END IF;
                IF NEW.reason='clear' AND prior.observation_id IS NULL THEN
                    RAISE EXCEPTION 'Market selection is already clear'; END IF;
            END IF;
            IF NEW.observation_id IS NOT NULL THEN
                SELECT * INTO chosen FROM app.market_observations WHERE owner_id=NEW.owner_id
                    AND id=NEW.observation_id;
                IF NOT FOUND OR {same_target} IS DISTINCT FROM {selected_target} OR
                    chosen.amount IS NULL OR chosen.amount<=0 OR
                    (chosen.kind='quote' AND chosen.adjustment<>'unadjusted') THEN
                    RAISE EXCEPTION 'Selected market evidence is unusable'; END IF;
                IF NEW.reason='correction' AND (prior.observation_id IS NULL OR
                    chosen.previous_id IS DISTINCT FROM prior.observation_id) THEN
                    RAISE EXCEPTION 'Selected correction is inconsistent'; END IF;
                IF current_user='trading_runtime' AND EXISTS (SELECT 1 FROM
                    app.market_observations WHERE owner_id=NEW.owner_id AND
                    previous_id=NEW.observation_id) THEN
                    RAISE EXCEPTION 'Selected market evidence is superseded'; END IF;
            END IF;
            RETURN NULL;
        END $f$
    """)
    # The lock is acquired before these reads, including direct SQL callers.
    op.execute("""
        CREATE FUNCTION app.guard_market_write() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE total bigint;
        BEGIN
            IF current_user='trading_runtime' THEN
                EXECUTE format('SELECT count(*) FROM app.%I WHERE owner_id=$1',TG_TABLE_NAME)
                    INTO total USING NEW.owner_id;
                IF total>=1000 THEN RAISE EXCEPTION 'Market evidence limit reached'; END IF;
                IF TG_TABLE_NAME='market_observations' THEN
                  IF NEW.previous_id IS NOT NULL THEN
                    IF NOT EXISTS (SELECT 1 FROM app.market_observations WHERE
                        owner_id=NEW.owner_id AND id=NEW.previous_id) OR EXISTS (SELECT 1 FROM
                        app.market_observations WHERE owner_id=NEW.owner_id AND
                        previous_id=NEW.previous_id) THEN
                        RAISE EXCEPTION 'Market correction predecessor is unavailable'; END IF;
                  END IF;
                END IF;
            END IF;
            RETURN NEW;
        END $f$
    """)
    for function in (
        "check_market_identity",
        "check_market_observation",
        "check_market_selection",
        "guard_market_write",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION app.{function}() FROM PUBLIC")
    for table in TABLES:
        function = (
            "check_market_observation"
            if table == "market_observations"
            else "check_market_selection"
        )
        for name in ("check_market_identity", function):
            op.execute(
                f"CREATE CONSTRAINT TRIGGER {name} AFTER INSERT ON app.{table} "
                f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.{name}()"
            )
        op.execute(
            f"CREATE TRIGGER b_guard_market_write BEFORE INSERT ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.guard_market_write()"
        )


def _privileges() -> None:
    columns = {
        "market_observations": (
            f"owner_id,id,previous_id,{TARGET},adjustment,namespace,"
            "digest_algorithm,digest,occurrence,normalizer,normalizer_version,contract_version,"
            "observed_on,observed_at,source,amount,missing_reason"
        ),
        "market_selections": (
            f"owner_id,id,revision,previous_revision,{TARGET},observation_id,reason"
        ),
    }
    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth")
        op.execute(f"""
            CREATE POLICY market_owner ON app.{table} TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
        """)
        op.execute(f"GRANT SELECT,INSERT ({columns[table]}) ON app.{table} TO trading_runtime")
        op.execute(
            f"CREATE TRIGGER a_serialize_financial_write BEFORE INSERT ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.serialize_financial_write()"
        )


def downgrade() -> None:
    op.execute("""
        DO $f$ BEGIN
            IF EXISTS (SELECT 1 FROM app.market_observations) OR
                EXISTS (SELECT 1 FROM app.market_selections) THEN
                RAISE EXCEPTION 'Market evidence cannot be downgraded'; END IF;
        END $f$
    """)
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    for signature in (
        "check_market_identity()",
        "check_market_observation()",
        "check_market_selection()",
        "guard_market_write()",
        "valid_market_target(text,uuid,uuid,text,text,text,text)",
        "valid_market_amount(text,numeric,text)",
    ):
        op.execute(f"DROP FUNCTION app.{signature}")
