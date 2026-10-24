"""Explicit securities, fund variants, listings, identifiers and position identities."""

from alembic import op

revision = "0007_instruments"
down_revision = "0006_accounts_sources"
branch_labels = None
depends_on = None

TABLES = (
    "fund_schemes",
    "instruments",
    "instrument_listings",
    "instrument_identifiers",
    "instrument_mappings",
    "account_positions",
)


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app.valid_isin(value text) RETURNS boolean
        LANGUAGE plpgsql IMMUTABLE STRICT SECURITY INVOKER SET search_path=pg_catalog
        AS $function$
        DECLARE expanded text := ''; character text; digit integer;
                total integer := 0; weight integer := 1; position integer;
        BEGIN
            IF value !~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$' OR length(value) <> 12 THEN
                RETURN false;
            END IF;
            FOR position IN 1..12 LOOP
                character := substr(value, position, 1);
                expanded := expanded || CASE WHEN character ~ '[A-Z]'
                    THEN (ascii(character)-55)::text ELSE character END;
            END LOOP;
            FOR position IN REVERSE length(expanded)..1 LOOP
                digit := substr(expanded, position, 1)::integer * weight;
                total := total + digit / 10 + digit % 10;
                weight := 3 - weight;
            END LOOP;
            RETURN total % 10 = 0;
        END
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.valid_isin(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION app.valid_isin(text) TO trading_runtime")
    op.execute("""
        CREATE TABLE app.fund_schemes (
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120
                AND name ~ '^[A-Za-z0-9][A-Za-z0-9 &().,/''-]*$'),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id)
        )
    """)
    op.execute("""
        CREATE TABLE app.instruments (
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            asset_class text NOT NULL CHECK (asset_class IN ('equity','etf','mutual_fund')),
            name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120
                AND name ~ '^[A-Za-z0-9][A-Za-z0-9 &().,/''-]*$'),
            isin text NOT NULL CHECK (app.valid_isin(isin)),
            fund_scheme_id uuid,
            fund_plan text,
            fund_option text,
            fund_currency text,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id), UNIQUE (owner_id,isin),
            FOREIGN KEY (owner_id,fund_scheme_id) REFERENCES app.fund_schemes(owner_id,id),
            CHECK ((asset_class='mutual_fund' AND fund_scheme_id IS NOT NULL
                    AND fund_plan IS NOT NULL AND fund_plan IN ('direct','regular')
                    AND fund_option IS NOT NULL
                    AND fund_option IN ('growth','idcw_payout','idcw_reinvestment')
                    AND fund_currency IS NOT NULL AND fund_currency='INR')
                OR (asset_class<>'mutual_fund' AND fund_scheme_id IS NULL AND fund_plan IS NULL
                    AND fund_option IS NULL AND fund_currency IS NULL))
        )
    """)
    op.execute("""
        CREATE TABLE app.instrument_listings (
            owner_id uuid NOT NULL,
            id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            instrument_id uuid NOT NULL,
            venue text NOT NULL,
            symbol text NOT NULL CHECK (length(symbol) BETWEEN 1 AND 32
                AND symbol ~ '^[A-Z0-9][A-Z0-9.&/-]*$'),
            series text NOT NULL CHECK (series ~ '^([A-Z0-9]{1,8})?$'),
            quote_currency text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id), UNIQUE (owner_id,id,instrument_id),
            UNIQUE (owner_id,instrument_id,venue,symbol,series,quote_currency),
            FOREIGN KEY (owner_id,instrument_id) REFERENCES app.instruments(owner_id,id),
            CHECK ((venue IN ('XNSE','XBOM') AND quote_currency='INR')
                OR (venue IN ('XNYS','XNAS','ARCX') AND quote_currency='USD'))
        )
    """)
    op.execute("""
        CREATE TABLE app.instrument_identifiers (
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            namespace text NOT NULL CHECK (namespace IN ('indmoney_india','indmoney_us',
                'indmoney_funds','ubs','amfi_nav')),
            value text NOT NULL CHECK (length(value) BETWEEN 1 AND 64
                AND value ~ '^[A-Za-z0-9][A-Za-z0-9._/-]*$'),
            qualifier text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id), UNIQUE (owner_id,namespace,value,qualifier),
            CHECK ((namespace='amfi_nav' AND value ~ '^[0-9]{1,12}$'
                    AND qualifier IN ('growth','idcw_payout','idcw_reinvestment'))
                OR (namespace<>'amfi_nav' AND qualifier=''))
        )
    """)
    op.execute("""
        CREATE TABLE app.instrument_mappings (
            owner_id uuid NOT NULL,
            identifier_id uuid NOT NULL,
            revision bigint NOT NULL CHECK (revision BETWEEN 1 AND 9007199254740991),
            previous_revision bigint,
            instrument_id uuid,
            listing_id uuid,
            reason text NOT NULL CHECK (reason IN ('initial','correction','unlinked')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,identifier_id,revision),
            FOREIGN KEY (owner_id,identifier_id) REFERENCES app.instrument_identifiers(owner_id,id),
            FOREIGN KEY (owner_id,instrument_id) REFERENCES app.instruments(owner_id,id),
            FOREIGN KEY (owner_id,listing_id,instrument_id)
                REFERENCES app.instrument_listings(owner_id,id,instrument_id),
            FOREIGN KEY (owner_id,identifier_id,previous_revision)
                REFERENCES app.instrument_mappings(owner_id,identifier_id,revision)
                DEFERRABLE INITIALLY DEFERRED,
            CHECK ((revision=1 AND previous_revision IS NULL AND reason='initial')
                OR (revision>1 AND previous_revision IS NOT NULL
                    AND previous_revision=revision-1 AND reason<>'initial')),
            CHECK ((instrument_id IS NULL AND listing_id IS NULL AND reason='unlinked')
                OR (instrument_id IS NOT NULL AND reason<>'unlinked'))
        )
    """)
    op.execute("""
        CREATE TABLE app.account_positions (
            owner_id uuid NOT NULL,
            id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
            account_id uuid NOT NULL,
            instrument_id uuid NOT NULL,
            holding_form text NOT NULL CHECK (holding_form IN ('folio','demat','custody')),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id), UNIQUE (owner_id,account_id,instrument_id,holding_form),
            FOREIGN KEY (owner_id,account_id) REFERENCES app.financial_accounts(owner_id,id),
            FOREIGN KEY (owner_id,instrument_id) REFERENCES app.instruments(owner_id,id)
        )
    """)
    op.execute("""
        CREATE FUNCTION app.validate_instrument_relation() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $function$
        DECLARE compatible boolean;
        BEGIN
            IF TG_TABLE_NAME='instrument_listings' THEN
                SELECT asset_class IN ('equity','etf') INTO compatible FROM app.instruments
                    WHERE owner_id=NEW.owner_id AND id=NEW.instrument_id;
            ELSIF TG_TABLE_NAME='account_positions' THEN
                SELECT CASE a.kind
                    WHEN 'mutual_fund' THEN i.asset_class='mutual_fund'
                        AND NEW.holding_form IN ('folio','demat')
                    WHEN 'brokerage' THEN (a.market='IN' AND NEW.holding_form='demat')
                        OR (a.market='US' AND NEW.holding_form='custody'
                            AND i.asset_class IN ('equity','etf'))
                    WHEN 'employee_stock' THEN i.asset_class='equity' AND NEW.holding_form='custody'
                    ELSE false END
                    AND (current_user<>'trading_runtime' OR a.archived_at IS NULL)
                    AND (i.asset_class<>'mutual_fund' OR EXISTS (
                        SELECT 1 FROM app.account_currencies c WHERE c.owner_id=a.owner_id
                            AND c.account_id=a.id AND c.currency=i.fund_currency))
                    INTO compatible FROM app.financial_accounts a JOIN app.instruments i
                        ON i.owner_id=a.owner_id
                    WHERE a.owner_id=NEW.owner_id AND a.id=NEW.account_id
                        AND i.id=NEW.instrument_id;
            ELSE
                IF NEW.instrument_id IS NULL THEN RETURN NEW; END IF;
                SELECT CASE r.namespace
                    WHEN 'indmoney_funds' THEN i.asset_class='mutual_fund'
                        AND NEW.listing_id IS NULL
                    WHEN 'amfi_nav' THEN i.asset_class='mutual_fund' AND NEW.listing_id IS NULL
                        AND i.fund_option=r.qualifier
                    WHEN 'ubs' THEN i.asset_class='equity'
                        AND (NEW.listing_id IS NULL OR l.quote_currency='USD')
                    WHEN 'indmoney_us' THEN i.asset_class IN ('equity','etf')
                        AND (NEW.listing_id IS NULL OR l.quote_currency='USD')
                    ELSE i.asset_class IN ('equity','etf')
                        AND (NEW.listing_id IS NULL OR l.quote_currency='INR') END
                    INTO compatible FROM app.instrument_identifiers r JOIN app.instruments i
                        ON i.owner_id=r.owner_id
                    LEFT JOIN app.instrument_listings l
                        ON l.owner_id=i.owner_id AND l.id=NEW.listing_id AND l.instrument_id=i.id
                    WHERE r.owner_id=NEW.owner_id AND r.id=NEW.identifier_id
                        AND i.id=NEW.instrument_id;
            END IF;
            IF compatible IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Instrument relation is unavailable';
            END IF;
            RETURN NEW;
        END
        $function$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.validate_instrument_relation() FROM PUBLIC")
    for table in ("instrument_listings", "instrument_mappings", "account_positions"):
        op.execute(f"""
            CREATE TRIGGER validate_instrument_relation BEFORE INSERT ON app.{table}
            FOR EACH ROW EXECUTE FUNCTION app.validate_instrument_relation()
        """)
    for table in TABLES:
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC, trading_runtime, trading_auth")
        op.execute(f"""
            CREATE POLICY instrument_owner ON app.{table} TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (
                SELECT 1 FROM app.owners WHERE id=app.current_owner_id() AND is_active))
        """)
        op.execute(f"GRANT SELECT ON app.{table} TO trading_runtime")
    columns = {
        "fund_schemes": "owner_id,id,name",
        "instruments": (
            "owner_id,id,asset_class,name,isin,fund_scheme_id,fund_plan,fund_option,fund_currency"
        ),
        "instrument_listings": "owner_id,id,instrument_id,venue,symbol,series,quote_currency",
        "instrument_identifiers": "owner_id,id,namespace,value,qualifier",
        "instrument_mappings": (
            "owner_id,identifier_id,revision,previous_revision,instrument_id,listing_id,reason"
        ),
        "account_positions": "owner_id,id,account_id,instrument_id,holding_form",
    }
    for table, names in columns.items():
        op.execute(f"GRANT INSERT ({names}) ON app.{table} TO trading_runtime")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    op.execute("DROP FUNCTION app.validate_instrument_relation()")
    op.execute("DROP FUNCTION app.valid_isin(text)")
