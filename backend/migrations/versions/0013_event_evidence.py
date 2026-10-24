"""Protected provider transaction identities and exact corroborating source links."""

from alembic import op

revision = "0013_event_evidence"
down_revision = "0012_market_evidence"
branch_labels = None
depends_on = None

TABLES = ("event_provider_identities", "event_evidence_links")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app.event_provider_identities (
            owner_id uuid NOT NULL REFERENCES app.owners(id),
            id uuid NOT NULL CHECK (id<>'00000000-0000-0000-0000-000000000000'),
            source_id uuid NOT NULL, kind text NOT NULL CHECK (kind IN ('buy','sell',
                'subscription','redemption','dividend','fee','withholding','cash_movement')),
            event_id uuid NOT NULL, event_revision bigint NOT NULL CHECK (event_revision=1),
            key_version integer NOT NULL CHECK (key_version BETWEEN 1 AND 2147483647),
            key_check text NOT NULL CHECK (length(key_check)=64 AND key_check ~ '^[0-9a-f]{64}$'),
            fingerprint text NOT NULL CHECK (length(fingerprint)=64 AND
                fingerprint ~ '^[0-9a-f]{64}$'),
            encrypted_reference text NOT NULL CHECK (length(encrypted_reference) BETWEEN 40 AND 256
                AND encrypted_reference ~ '^[A-Za-z0-9_-]+={0,2}$'),
            key_revision bigint NOT NULL DEFAULT 1 CHECK
                (key_revision BETWEEN 1 AND 9007199254740991),
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,id), UNIQUE (owner_id,event_id), UNIQUE (owner_id,id,event_id),
            UNIQUE (owner_id,source_id,kind,key_version,fingerprint),
            FOREIGN KEY (owner_id,source_id) REFERENCES app.source_accounts(owner_id,id),
            FOREIGN KEY (owner_id,event_id,event_revision) REFERENCES
                app.financial_events(owner_id,id,revision) DEFERRABLE INITIALLY DEFERRED
        )
    """)
    op.execute("""
        CREATE TABLE app.event_evidence_links (
            owner_id uuid NOT NULL REFERENCES app.owners(id), source_row_id uuid NOT NULL,
            review_revision bigint NOT NULL, identity_id uuid NOT NULL,
            event_id uuid NOT NULL, event_revision bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
            PRIMARY KEY (owner_id,source_row_id),
            FOREIGN KEY (owner_id,source_row_id,review_revision) REFERENCES
                app.review_decisions(owner_id,row_id,revision) DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (owner_id,identity_id,event_id) REFERENCES
                app.event_provider_identities(owner_id,id,event_id) DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (owner_id,event_id,event_revision) REFERENCES
                app.financial_events(owner_id,id,revision) DEFERRABLE INITIALLY DEFERRED
        )
    """)
    op.execute(
        "CREATE INDEX event_evidence_event ON app.event_evidence_links"
        "(owner_id,event_id,source_row_id)"
    )
    _integrity()
    _consumption()
    _privileges()


def _integrity() -> None:
    op.execute("""
        CREATE FUNCTION app.check_provider_identity() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM app.financial_events e JOIN app.staged_rows r
                ON r.owner_id=e.owner_id AND r.id=e.source_row_id JOIN app.import_batches b
                ON b.owner_id=r.owner_id AND b.id=r.batch_id JOIN app.source_observations o
                ON o.owner_id=b.owner_id AND o.id=b.observation_id WHERE e.owner_id=NEW.owner_id
                AND e.id=NEW.event_id AND e.revision=NEW.event_revision AND e.kind=NEW.kind
                AND o.source_id=NEW.source_id) THEN
                RAISE EXCEPTION 'Provider event identity is inconsistent'; END IF;
            RETURN NULL;
        END $f$
    """)
    op.execute("""
        CREATE FUNCTION app.check_event_evidence() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE e app.financial_events%ROWTYPE; s app.staged_rows%ROWTYPE;
                p app.event_provider_identities%ROWTYPE;
        BEGIN
            SELECT * INTO e FROM app.financial_events WHERE owner_id=NEW.owner_id
                AND id=NEW.event_id AND revision=NEW.event_revision;
            SELECT * INTO s FROM app.staged_rows WHERE owner_id=NEW.owner_id
                AND id=NEW.source_row_id;
            SELECT * INTO p FROM app.event_provider_identities WHERE owner_id=NEW.owner_id
                AND id=NEW.identity_id;
            IF e.id IS NULL OR s.id IS NULL OR p.id IS NULL OR p.event_id<>e.id OR
                e.status<>'active' OR (s.kind,s.posting_state,s.trade_date,s.settlement_date,
                s.booking_date,s.value_date) IS DISTINCT FROM (e.kind,e.posting_state,e.trade_date,
                e.settlement_date,e.booking_date,e.value_date)
                OR p.kind<>s.kind OR NOT EXISTS (SELECT 1 FROM app.import_batches b
                    JOIN app.source_observations o ON o.owner_id=b.owner_id
                        AND o.id=b.observation_id
                    WHERE b.owner_id=NEW.owner_id AND b.id=s.batch_id AND o.source_id=p.source_id)
                THEN RAISE EXCEPTION 'Event evidence identity is inconsistent'; END IF;
            PERFORM app.check_record_review(NEW.owner_id,NEW.source_row_id,NEW.review_revision,
                e.account_id,e.instrument_id,false);
            IF EXISTS ((SELECT role,amount,currency,missing_reason FROM app.staged_values
                    WHERE owner_id=NEW.owner_id AND row_id=NEW.source_row_id)
                EXCEPT (SELECT role,amount,currency,missing_reason FROM app.event_components
                    WHERE owner_id=NEW.owner_id AND event_id=e.id AND revision=e.revision))
                OR EXISTS ((SELECT role,amount,currency,missing_reason FROM app.event_components
                    WHERE owner_id=NEW.owner_id AND event_id=e.id AND revision=e.revision)
                EXCEPT (SELECT role,amount,currency,missing_reason FROM app.staged_values
                    WHERE owner_id=NEW.owner_id AND row_id=NEW.source_row_id)) THEN
                RAISE EXCEPTION 'Event evidence economics differ'; END IF;
            RETURN NULL;
        END $f$
    """)
    op.execute("""
        CREATE FUNCTION app.guard_event_evidence_write() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE total bigint;
        BEGIN
            IF TG_OP='UPDATE' THEN
                IF NEW.key_version<=OLD.key_version THEN
                    RAISE EXCEPTION 'Provider key rotation must advance'; END IF;
                NEW.key_revision:=OLD.key_revision+1;
                NEW.updated_at:=statement_timestamp();
            ELSIF current_user='trading_runtime' THEN
                EXECUTE format('SELECT count(*) FROM app.%I WHERE owner_id=$1',TG_TABLE_NAME)
                    INTO total USING NEW.owner_id;
                IF total>=1000 THEN RAISE EXCEPTION 'Event evidence limit reached'; END IF;
                IF TG_TABLE_NAME='event_evidence_links' THEN
                    IF NOT EXISTS (SELECT 1 FROM app.financial_events WHERE owner_id=NEW.owner_id
                        AND id=NEW.event_id AND revision=NEW.event_revision) OR
                        EXISTS (SELECT 1 FROM app.financial_events WHERE owner_id=NEW.owner_id
                        AND id=NEW.event_id AND revision>NEW.event_revision) THEN
                        RAISE EXCEPTION 'Event evidence target is stale'; END IF;
                END IF;
            END IF;
            RETURN NEW;
        END $f$
    """)
    for table, function in zip(
        TABLES, ("check_provider_identity", "check_event_evidence"), strict=True
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {function} AFTER INSERT ON app.{table} "
            f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.{function}()"
        )
        operations = "INSERT OR UPDATE" if table == TABLES[0] else "INSERT"
        op.execute(
            f"CREATE TRIGGER b_guard_event_evidence BEFORE {operations} ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.guard_event_evidence_write()"
        )


def _consumption() -> None:
    op.execute("""
        CREATE FUNCTION app.check_event_link_consumption() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE link app.event_evidence_links%ROWTYPE;
        BEGIN
            SELECT * INTO link FROM app.event_evidence_links WHERE owner_id=NEW.owner_id
                AND source_row_id=NEW.source_row_id;
            IF FOUND AND (EXISTS (SELECT 1 FROM app.lot_observations WHERE owner_id=NEW.owner_id
                    AND source_row_id=NEW.source_row_id) OR
                EXISTS (SELECT 1 FROM app.snapshot_records WHERE owner_id=NEW.owner_id
                    AND source_row_id=NEW.source_row_id) OR
                EXISTS (SELECT 1 FROM app.financial_events WHERE owner_id=NEW.owner_id
                    AND source_row_id=NEW.source_row_id AND (id,revision) IS DISTINCT FROM
                    (link.event_id,link.event_revision))) THEN
                RAISE EXCEPTION 'Source occurrence already has an economic disposition'; END IF;
            RETURN NULL;
        END $f$
    """)
    for table in (
        "financial_events",
        "lot_observations",
        "snapshot_records",
        "event_evidence_links",
    ):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER check_event_link_consumption AFTER INSERT ON app.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "app.check_event_link_consumption()"
        )
    op.execute("""
        CREATE FUNCTION app.guard_event_link_review() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        BEGIN
            IF current_user='trading_runtime' AND EXISTS (SELECT 1 FROM app.event_evidence_links
                WHERE owner_id=NEW.owner_id AND source_row_id=NEW.row_id) THEN
                RAISE EXCEPTION 'Linked event evidence review is immutable'; END IF;
            RETURN NEW;
        END $f$
    """)
    op.execute(
        "CREATE TRIGGER guard_event_link_review BEFORE INSERT ON app.review_decisions "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_event_link_review()"
    )


def _privileges() -> None:
    for function in (
        "check_provider_identity",
        "check_event_evidence",
        "guard_event_evidence_write",
        "check_event_link_consumption",
        "guard_event_link_review",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION app.{function}() FROM PUBLIC")
    columns = (
        "owner_id,id,source_id,kind,event_id,event_revision,key_version,key_check,fingerprint,encrypted_reference",
        "owner_id,source_row_id,review_revision,identity_id,event_id,event_revision",
    )
    for table, fields in zip(TABLES, columns, strict=True):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth")
        op.execute(f"""
            CREATE POLICY event_evidence_owner ON app.{table} TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
        """)
        op.execute(f"GRANT SELECT,INSERT ({fields}) ON app.{table} TO trading_runtime")
        operations = "INSERT OR UPDATE" if table == TABLES[0] else "INSERT"
        op.execute(
            f"CREATE TRIGGER a_serialize_financial_write BEFORE {operations} ON app.{table} "
            "FOR EACH ROW EXECUTE FUNCTION app.serialize_financial_write()"
        )
    op.execute(
        "GRANT UPDATE (key_version,key_check,fingerprint,encrypted_reference) "
        "ON app.event_provider_identities TO trading_runtime"
    )


def downgrade() -> None:
    op.execute("""
        DO $f$ BEGIN
            IF EXISTS (SELECT 1 FROM app.event_provider_identities) OR
                EXISTS (SELECT 1 FROM app.event_evidence_links) THEN
                RAISE EXCEPTION 'Provider event evidence cannot be downgraded'; END IF;
        END $f$
    """)
    for table in (
        "financial_events",
        "lot_observations",
        "snapshot_records",
        "event_evidence_links",
    ):
        op.execute(f"DROP TRIGGER check_event_link_consumption ON app.{table}")
    op.execute("DROP TRIGGER guard_event_link_review ON app.review_decisions")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    for function in (
        "check_provider_identity",
        "check_event_evidence",
        "guard_event_evidence_write",
        "check_event_link_consumption",
        "guard_event_link_review",
    ):
        op.execute(f"DROP FUNCTION app.{function}()")
