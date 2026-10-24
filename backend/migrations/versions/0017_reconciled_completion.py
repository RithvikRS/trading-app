"""Exact native reconciliation with immutable source and combined comparison inputs."""

from alembic import op

revision = "0017_reconciled_completion"
down_revision = "0016_completion_receipts"
branch_labels = None
depends_on = None

TABLES = ("completion_scopes", "completion_inputs")
HELPERS = (
    "reconciliation_source_inputs(uuid,uuid)",
    "reconciliation_current_activity(uuid,uuid,uuid,text,date,date,text)",
    "validate_completion_scope(uuid,uuid)",
)

PREVIOUS_GUARD = """
CREATE OR REPLACE FUNCTION app.guard_completion_receipt() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path=pg_catalog AS $f$
DECLARE doc jsonb; batch record;
BEGIN
 IF octet_length(NEW.request_canonical) NOT BETWEEN 2 AND 65536 THEN
  RAISE EXCEPTION 'Completion request exceeds its bounded manifest'; END IF;
 doc := NEW.request_canonical::jsonb;
 IF app.valid_completion_manifest(doc) IS NOT TRUE THEN
  RAISE EXCEPTION 'Completion request is unavailable'; END IF;
 IF app.completion_canonical(doc)<>NEW.request_canonical OR
  (doc->>'idempotency_key')::uuid<>NEW.idempotency_key OR
  (doc->>'batch_id')::uuid<>NEW.batch_id OR
  (doc->>'batch_revision')::bigint<>NEW.batch_revision OR
  doc->>'baseline'<>NEW.baseline_digest OR doc->>'mode'<>NEW.mode OR
  jsonb_array_length(doc->'rows')<>NEW.row_count OR
  jsonb_array_length(doc->'selections')<>NEW.selection_count THEN
  RAISE EXCEPTION 'Completion request differs from its receipt'; END IF;
 SELECT b.*,o.coverage INTO batch FROM app.import_batches b JOIN app.source_observations o
  ON o.owner_id=b.owner_id AND o.id=b.observation_id WHERE b.owner_id=NEW.owner_id AND
    b.id=NEW.batch_id;
 IF NOT FOUND OR batch.revision<>NEW.batch_revision OR batch.coverage<>NEW.coverage OR
  NEW.coverage='complete_activity' THEN RAISE EXCEPTION 'Completion coverage is unavailable';
    END IF;
 IF current_user='trading_runtime' THEN
  IF app.financial_baseline()<>NEW.baseline_digest OR
   EXISTS (SELECT 1 FROM app.import_batches WHERE owner_id=NEW.owner_id AND
    observation_id=batch.observation_id AND revision>batch.revision) OR
   EXISTS (SELECT 1 FROM app.source_observations WHERE owner_id=NEW.owner_id AND
    previous_id=batch.observation_id) THEN
   RAISE EXCEPTION 'Completion preview is stale'; END IF;
 END IF;
 RETURN NEW;
END $f$;
"""

CURRENT_GUARD = """
CREATE OR REPLACE FUNCTION app.guard_completion_receipt() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path=pg_catalog AS $f$
DECLARE doc jsonb; batch record;
BEGIN
 IF octet_length(NEW.request_canonical) NOT BETWEEN 2 AND 65536 THEN
  RAISE EXCEPTION 'Completion request exceeds its bounded manifest'; END IF;
 doc := NEW.request_canonical::jsonb;
 IF app.valid_completion_manifest(doc) IS NOT TRUE THEN
  RAISE EXCEPTION 'Completion request is unavailable'; END IF;
 IF app.completion_canonical(doc)<>NEW.request_canonical OR
  (doc->>'idempotency_key')::uuid<>NEW.idempotency_key OR
  (doc->>'batch_id')::uuid<>NEW.batch_id OR
  (doc->>'batch_revision')::bigint<>NEW.batch_revision OR
  doc->>'baseline'<>NEW.baseline_digest OR doc->>'mode'<>NEW.mode OR
  jsonb_array_length(doc->'rows')<>NEW.row_count OR
  jsonb_array_length(doc->'selections')<>NEW.selection_count THEN
  RAISE EXCEPTION 'Completion request differs from its receipt'; END IF;
 SELECT b.*,o.coverage INTO batch FROM app.import_batches b JOIN app.source_observations o
  ON o.owner_id=b.owner_id AND o.id=b.observation_id WHERE b.owner_id=NEW.owner_id AND
    b.id=NEW.batch_id;
 IF NOT FOUND OR batch.revision<>NEW.batch_revision OR batch.coverage<>NEW.coverage OR
  ((NEW.mode='limited' AND NEW.coverage='complete_activity') OR
   (NEW.mode='reconciled' AND NEW.coverage<>'complete_activity')) THEN
   RAISE EXCEPTION 'Completion coverage is unavailable';
    END IF;
 IF current_user='trading_runtime' THEN
  IF app.financial_baseline()<>NEW.baseline_digest OR
   EXISTS (SELECT 1 FROM app.import_batches WHERE owner_id=NEW.owner_id AND
    observation_id=batch.observation_id AND revision>batch.revision) OR
   EXISTS (SELECT 1 FROM app.source_observations WHERE owner_id=NEW.owner_id AND
    previous_id=batch.observation_id) THEN
   RAISE EXCEPTION 'Completion preview is stale'; END IF;
 END IF;
 RETURN NEW;
END $f$;
"""

TABLE_SQL = """
CREATE TABLE app.completion_scopes (
 owner_id uuid NOT NULL, id uuid NOT NULL CHECK (id<>'00000000-0000-0000-0000-000000000000'),
 receipt_id uuid NOT NULL, kind text NOT NULL CHECK (kind IN ('cash','units')),
 account_id uuid NOT NULL, position_id uuid, currency text,
 period_start date NOT NULL, period_end date NOT NULL CHECK (period_start<=period_end),
 date_basis text NOT NULL, rule_version smallint NOT NULL CHECK (rule_version=1),
 opening_amount numeric NOT NULL, closing_amount numeric NOT NULL,
 source_total numeric NOT NULL, combined_total numeric NOT NULL,
 source_posted_count integer NOT NULL CHECK (source_posted_count BETWEEN 0 AND 100),
 source_pending_count integer NOT NULL CHECK (source_pending_count BETWEEN 0 AND 100),
 combined_posted_count integer NOT NULL CHECK (combined_posted_count BETWEEN 0 AND 1000),
 combined_pending_count integer NOT NULL CHECK (combined_pending_count BETWEEN 0 AND 1000),
 input_count integer NOT NULL CHECK (input_count BETWEEN 4 AND 1000),
 PRIMARY KEY (owner_id,id),
 UNIQUE NULLS NOT DISTINCT (owner_id,receipt_id,account_id,position_id,currency),
 FOREIGN KEY (owner_id,receipt_id) REFERENCES app.completion_receipts(owner_id,id),
 FOREIGN KEY (owner_id,account_id) REFERENCES app.financial_accounts(owner_id,id),
 FOREIGN KEY (owner_id,position_id) REFERENCES app.account_positions(owner_id,id),
 CHECK ((kind='cash' AND position_id IS NULL AND currency IS NOT NULL AND
   currency IN ('INR','USD') AND date_basis IN ('booking','value','settlement')) OR
  (kind='units' AND position_id IS NOT NULL AND currency IS NULL AND date_basis='trade')),
 CHECK (opening_amount<>'NaN'::numeric AND abs(opening_amount)<1e18 AND
  scale(opening_amount)<=CASE kind WHEN 'cash' THEN 2 ELSE 12 END AND
  (kind='cash' OR opening_amount>=0)),
 CHECK (closing_amount<>'NaN'::numeric AND abs(closing_amount)<1e18 AND
  scale(closing_amount)<=CASE kind WHEN 'cash' THEN 2 ELSE 12 END AND
  (kind='cash' OR closing_amount>=0)),
 CHECK (source_total<>'NaN'::numeric AND abs(source_total)<1e22 AND
  scale(source_total)<=CASE kind WHEN 'cash' THEN 2 ELSE 12 END),
 CHECK (combined_total<>'NaN'::numeric AND abs(combined_total)<1e22 AND
  scale(combined_total)<=CASE kind WHEN 'cash' THEN 2 ELSE 12 END),
 CHECK (opening_amount+source_total=closing_amount AND
        opening_amount+combined_total=closing_amount)
);

CREATE TABLE app.completion_inputs (
 owner_id uuid NOT NULL, scope_id uuid NOT NULL,
 side text NOT NULL CHECK (side IN ('source','combined')),
 part text NOT NULL CHECK (part IN ('opening','closing','activity')),
 reference_id uuid NOT NULL, reference_revision bigint NOT NULL,
 source_row_id uuid, event_id uuid, snapshot_id uuid,
 source text NOT NULL CHECK (octet_length(source) BETWEEN 1 AND 32),
 amount numeric NOT NULL CHECK (amount<>'NaN'::numeric AND abs(amount)<1e18 AND scale(amount)<=12),
 evidence_date date, posting_state text,
 PRIMARY KEY (owner_id,scope_id,side,reference_id),
 FOREIGN KEY (owner_id,scope_id) REFERENCES app.completion_scopes(owner_id,id),
 FOREIGN KEY (owner_id,source_row_id,reference_revision)
  REFERENCES app.review_decisions(owner_id,row_id,revision),
 FOREIGN KEY (owner_id,event_id,reference_revision)
  REFERENCES app.financial_events(owner_id,id,revision),
 FOREIGN KEY (owner_id,snapshot_id,reference_revision)
  REFERENCES app.snapshot_records(owner_id,id,revision),
 CHECK ((side='source' AND source_row_id IS NOT NULL AND reference_id=source_row_id AND
   event_id IS NULL AND snapshot_id IS NULL) OR
  (side='combined' AND source_row_id IS NULL AND
   ((part='activity' AND event_id IS NOT NULL AND reference_id=event_id AND snapshot_id IS NULL) OR
    (part IN ('opening','closing') AND snapshot_id IS NOT NULL AND reference_id=snapshot_id
      AND event_id IS NULL)))),
 CHECK ((part='activity' AND posting_state IS NOT NULL AND posting_state IN ('posted','pending')) OR
  (part IN ('opening','closing') AND posting_state IS NULL AND evidence_date IS NOT NULL))
);
CREATE INDEX completion_scope_receipt ON app.completion_scopes(owner_id,receipt_id,id);

"""

QUERIES = """
CREATE FUNCTION app.reconciliation_source_inputs(own uuid,receipt_key uuid)
RETURNS TABLE(kind text,account_id uuid,position_id uuid,currency text,side text,part text,
 reference_id uuid,reference_revision bigint,source_row_id uuid,event_id uuid,snapshot_id uuid,
 source text,amount numeric,evidence_date date,posting_state text)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $f$
 WITH evidence AS (
  SELECT cr.source_row_id,cr.review_revision,cr.snapshot_id,cr.record_revision,
   COALESCE(e.account_id,s.account_id) AS account_id,
   COALESCE(e.position_id,s.position_id) AS position_id,
   r.kind,r.reconciliation_boundary,r.as_of_date,r.posting_state,
   r.trade_date,r.booking_date,r.value_date,r.settlement_date,b.cash_date_basis,
   v.role,v.currency,v.source,v.amount
  FROM app.completion_receipts c JOIN app.import_batches b ON
   b.owner_id=c.owner_id AND b.id=c.batch_id
  JOIN app.completion_rows cr ON cr.owner_id=c.owner_id AND cr.receipt_id=c.id
  JOIN app.staged_rows r ON r.owner_id=cr.owner_id AND r.id=cr.source_row_id
  JOIN app.staged_values v ON v.owner_id=r.owner_id AND v.row_id=r.id
  LEFT JOIN app.financial_events e ON e.owner_id=cr.owner_id AND e.id=cr.event_id
   AND e.revision=cr.record_revision
  LEFT JOIN app.snapshot_records s ON s.owner_id=cr.owner_id AND s.id=cr.snapshot_id
   AND s.revision=cr.record_revision
  WHERE c.owner_id=own AND c.id=receipt_key AND
   ((r.kind IN ('buy','sell','subscription','redemption','cash_movement','dividend','fee',
      'withholding') AND v.role IN ('net_cash','quantity')) OR
    (r.kind='cash_snapshot' AND v.role='net_cash') OR
    (r.kind='position_snapshot' AND v.role='quantity'))
 ), inputs AS (
  SELECT CASE WHEN role='net_cash' THEN 'cash' ELSE 'units' END AS kind,account_id,
   CASE WHEN role='quantity' THEN position_id END AS position_id,
   CASE WHEN role='net_cash' THEN currency END AS currency,
   CASE WHEN snapshot_id IS NULL THEN 'activity'
        WHEN reconciliation_boundary='before_period' THEN 'opening'
        WHEN reconciliation_boundary='after_period' THEN 'closing' ELSE 'unknown' END AS part,
   source_row_id,review_revision,snapshot_id,record_revision,source,amount,
   CASE WHEN snapshot_id IS NOT NULL THEN as_of_date WHEN role='quantity' THEN trade_date
    WHEN cash_date_basis='booking' THEN booking_date WHEN cash_date_basis='value' THEN value_date
    WHEN cash_date_basis='settlement' THEN settlement_date END AS evidence_date,
   CASE WHEN snapshot_id IS NULL THEN posting_state END AS posting_state
  FROM evidence
 )
 SELECT kind,account_id,position_id,currency,'source',part,source_row_id,review_revision,
  source_row_id,NULL::uuid,NULL::uuid,source,amount,evidence_date,posting_state FROM inputs
 UNION ALL
 SELECT kind,account_id,position_id,currency,'combined',part,snapshot_id,record_revision,
  NULL::uuid,NULL::uuid,snapshot_id,source,amount,evidence_date,NULL::text FROM inputs
  WHERE snapshot_id IS NOT NULL
$f$;

CREATE FUNCTION app.reconciliation_current_activity(own uuid,account_key uuid,
 position_key uuid,native_currency text,first_day date,last_day date,basis text)
RETURNS TABLE(reference_id uuid,reference_revision bigint,source text,amount numeric,
 evidence_date date,posting_state text)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $f$
 SELECT e.id,e.revision,v.source,v.amount,d.day,e.posting_state
 FROM app.financial_events e JOIN app.event_components v ON v.owner_id=e.owner_id
  AND v.event_id=e.id AND v.revision=e.revision
 CROSS JOIN LATERAL (SELECT CASE basis WHEN 'trade' THEN e.trade_date
  WHEN 'booking' THEN e.booking_date WHEN 'value' THEN e.value_date
  WHEN 'settlement' THEN e.settlement_date END AS day) d
 WHERE e.owner_id=own AND e.account_id=account_key AND e.status='active' AND
  NOT EXISTS (SELECT 1 FROM app.financial_events n WHERE n.owner_id=e.owner_id AND
   n.id=e.id AND n.revision>e.revision) AND
  ((position_key IS NULL AND native_currency IS NOT NULL AND v.role='net_cash' AND
     v.currency=native_currency AND basis IN ('booking','value','settlement')) OR
   (position_key IS NOT NULL AND native_currency IS NULL AND e.position_id=position_key
    AND v.role='quantity' AND basis='trade')) AND
  (d.day IS NULL OR d.day BETWEEN first_day AND last_day)
$f$;

"""

CHECKS = """
CREATE FUNCTION app.check_reconciled_receipt() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
DECLARE source_record record;
BEGIN
 IF NEW.mode='limited' THEN
  IF EXISTS (SELECT 1 FROM app.completion_scopes WHERE owner_id=NEW.owner_id AND receipt_id=NEW.id)
   THEN RAISE EXCEPTION 'Limited receipt cannot declare reconciliation'; END IF;
  RETURN NULL;
 END IF;
 SELECT b.*,o.period_start,o.period_end INTO source_record FROM app.import_batches b
  JOIN app.source_observations o ON o.owner_id=b.owner_id AND o.id=b.observation_id
  WHERE b.owner_id=NEW.owner_id AND b.id=NEW.batch_id;
 IF NEW.coverage<>'complete_activity' OR source_record.period_start IS NULL OR
  source_record.period_end IS NULL OR EXISTS (
   SELECT 1 FROM app.completion_rows cr JOIN app.staged_rows r
    ON r.owner_id=cr.owner_id AND r.id=cr.source_row_id
   WHERE cr.owner_id=NEW.owner_id AND cr.receipt_id=NEW.id AND
    (cr.operation='exclude' OR r.kind IN ('unsupported','cancellation') OR
     (r.kind IN ('cash_snapshot','position_snapshot') AND
      (r.reconciliation_boundary IS NULL OR r.snapshot_scope IS DISTINCT FROM
        CASE r.kind WHEN 'cash_snapshot' THEN 'native_cash' ELSE 'selected_position' END))))
  THEN RAISE EXCEPTION 'Complete source evidence is unavailable'; END IF;
 IF NOT EXISTS (SELECT 1 FROM app.completion_scopes WHERE owner_id=NEW.owner_id
   AND receipt_id=NEW.id)
  OR EXISTS ((SELECT kind,account_id,position_id,currency
    FROM app.reconciliation_source_inputs(NEW.owner_id,NEW.id) WHERE side='source') EXCEPT
   (SELECT kind,account_id,position_id,currency FROM app.completion_scopes WHERE
    owner_id=NEW.owner_id AND receipt_id=NEW.id)) OR
  EXISTS ((SELECT kind,account_id,position_id,currency FROM app.completion_scopes WHERE
    owner_id=NEW.owner_id AND receipt_id=NEW.id) EXCEPT
   (SELECT kind,account_id,position_id,currency
    FROM app.reconciliation_source_inputs(NEW.owner_id,NEW.id) WHERE side='source')) THEN
   RAISE EXCEPTION 'Reconciliation scopes are incomplete'; END IF;
 RETURN NULL;
END $f$;

CREATE FUNCTION app.validate_completion_scope(own uuid,scope_key uuid) RETURNS void
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
DECLARE scoped app.completion_scopes%ROWTYPE; header record; metrics record; evidence record;
BEGIN
 SELECT * INTO scoped FROM app.completion_scopes WHERE owner_id=own AND id=scope_key;
 SELECT c.mode,b.cash_date_basis,o.period_start,o.period_end INTO header
  FROM app.completion_receipts c JOIN app.import_batches b
   ON b.owner_id=c.owner_id AND b.id=c.batch_id JOIN app.source_observations o
   ON o.owner_id=b.owner_id AND o.id=b.observation_id
  WHERE c.owner_id=own AND c.id=scoped.receipt_id;
 IF scoped.id IS NULL OR header.mode IS DISTINCT FROM 'reconciled' OR
  (scoped.period_start,scoped.period_end) IS DISTINCT FROM
   (header.period_start,header.period_end) OR scoped.date_basis IS DISTINCT FROM
    (CASE scoped.kind WHEN 'cash' THEN header.cash_date_basis ELSE 'trade' END) OR
  NOT EXISTS (SELECT 1 FROM app.reconciliation_source_inputs(own,scoped.receipt_id) x WHERE
   (x.kind,x.account_id,x.position_id,x.currency) IS NOT DISTINCT FROM
    (scoped.kind,scoped.account_id,scoped.position_id,scoped.currency)) OR
  (SELECT count(*) FROM app.completion_inputs WHERE owner_id=own AND scope_id=scope_key)
   <>scoped.input_count THEN RAISE EXCEPTION 'Reconciliation scope differs from its source'; END IF;

 -- Symmetric exact set comparison includes source amounts and original strings.
 -- It also fixes both combined checkpoint references to the completed snapshots.
 IF EXISTS ((SELECT x.side,x.part,x.reference_id,x.reference_revision,x.source_row_id,
    x.event_id,x.snapshot_id,x.source,x.amount,x.evidence_date,x.posting_state
   FROM app.reconciliation_source_inputs(own,scoped.receipt_id) x WHERE
    (x.kind,x.account_id,x.position_id,x.currency) IS NOT DISTINCT FROM
     (scoped.kind,scoped.account_id,scoped.position_id,scoped.currency)) EXCEPT
  (SELECT side,part,reference_id,reference_revision,source_row_id,event_id,snapshot_id,
    source,amount,evidence_date,posting_state FROM app.completion_inputs WHERE owner_id=own AND
     scope_id=scope_key AND (side='source' OR part<>'activity'))) OR
 EXISTS ((SELECT side,part,reference_id,reference_revision,source_row_id,event_id,snapshot_id,
    source,amount,evidence_date,posting_state FROM app.completion_inputs WHERE owner_id=own AND
     scope_id=scope_key AND (side='source' OR part<>'activity')) EXCEPT
  (SELECT x.side,x.part,x.reference_id,x.reference_revision,x.source_row_id,
    x.event_id,x.snapshot_id,x.source,x.amount,x.evidence_date,x.posting_state
   FROM app.reconciliation_source_inputs(own,scoped.receipt_id) x WHERE
    (x.kind,x.account_id,x.position_id,x.currency) IS NOT DISTINCT FROM
     (scoped.kind,scoped.account_id,scoped.position_id,scoped.currency))) THEN
  RAISE EXCEPTION 'Reconciliation inputs differ from their source'; END IF;

 -- Validate every historical combined movement even during trusted recovery.
 IF EXISTS (SELECT 1 FROM app.completion_inputs i WHERE i.owner_id=own AND i.scope_id=scope_key
  AND i.side='combined' AND i.part='activity' AND NOT EXISTS (
   SELECT 1 FROM app.financial_events e JOIN app.event_components v ON v.owner_id=e.owner_id
    AND v.event_id=e.id AND v.revision=e.revision
   WHERE e.owner_id=own AND e.id=i.event_id AND e.revision=i.reference_revision
    AND e.status='active' AND e.account_id=scoped.account_id
    AND ((scoped.kind='cash' AND v.role='net_cash' AND v.currency=scoped.currency) OR
     (scoped.kind='units' AND v.role='quantity' AND e.position_id=scoped.position_id))
    AND (i.source,i.amount,i.posting_state,i.evidence_date) IS NOT DISTINCT FROM
     (v.source,v.amount,e.posting_state,CASE scoped.date_basis WHEN 'trade' THEN e.trade_date
       WHEN 'booking' THEN e.booking_date WHEN 'value' THEN e.value_date
       WHEN 'settlement' THEN e.settlement_date END))) THEN
  RAISE EXCEPTION 'Combined input differs from its historical event'; END IF;

 -- Runtime completeness must not be inferred from a balanced sum: omissions of
 -- opposite signed movements would otherwise produce the same total.
 IF current_user='trading_runtime' AND (
  EXISTS ((SELECT * FROM app.reconciliation_current_activity(own,scoped.account_id,
    scoped.position_id,scoped.currency,scoped.period_start,scoped.period_end,scoped.date_basis))
   EXCEPT (SELECT reference_id,reference_revision,source,amount,evidence_date,posting_state
    FROM app.completion_inputs WHERE owner_id=own AND scope_id=scope_key AND
     side='combined' AND part='activity')) OR
  EXISTS ((SELECT reference_id,reference_revision,source,amount,evidence_date,posting_state
    FROM app.completion_inputs WHERE owner_id=own AND scope_id=scope_key AND
     side='combined' AND part='activity') EXCEPT
   (SELECT * FROM app.reconciliation_current_activity(own,scoped.account_id,
    scoped.position_id,scoped.currency,scoped.period_start,scoped.period_end,scoped.date_basis))))
  THEN RAISE EXCEPTION 'Combined reconciliation is incomplete'; END IF;

 IF EXISTS (SELECT 1 FROM app.completion_inputs WHERE owner_id=own AND scope_id=scope_key AND
  ((part='opening' AND evidence_date IS DISTINCT FROM scoped.period_start) OR
   (part='closing' AND evidence_date IS DISTINCT FROM scoped.period_end) OR
   (part='activity' AND ((posting_state='posted' AND evidence_date IS NULL) OR
     evidence_date NOT BETWEEN scoped.period_start AND scoped.period_end)) OR
   scale(amount)>CASE scoped.kind WHEN 'cash' THEN 2 ELSE 12 END)) THEN
  RAISE EXCEPTION 'Reconciliation dates or native amounts are unavailable'; END IF;

 -- Fees and withholding are independent evidence, never extra net cash legs.
 IF scoped.kind='cash' AND EXISTS (
  SELECT 1 FROM app.completion_inputs i WHERE i.owner_id=own AND i.scope_id=scope_key
   AND i.part='activity' AND
   ((i.side='source' AND EXISTS (SELECT 1 FROM app.staged_values v WHERE v.owner_id=own
     AND v.row_id=i.source_row_id AND v.role IN ('fee','withholding') AND v.amount IS NULL)) OR
    (i.side='combined' AND EXISTS (SELECT 1 FROM app.event_components v WHERE v.owner_id=own
     AND v.event_id=i.event_id AND v.revision=i.reference_revision
     AND v.role IN ('fee','withholding') AND v.amount IS NULL)))) THEN
  RAISE EXCEPTION 'Reconciliation contains unresolved cash components'; END IF;

 IF current_user='trading_runtime' THEN
  FOR evidence IN SELECT i.* FROM app.completion_inputs i WHERE i.owner_id=own AND
   i.scope_id=scope_key AND i.side='combined' AND i.part IN ('opening','closing') LOOP
   IF NOT EXISTS (SELECT 1 FROM app.snapshot_records s WHERE s.owner_id=own AND
      s.id=evidence.snapshot_id AND s.revision=evidence.reference_revision AND s.status='active'
      AND NOT EXISTS (SELECT 1 FROM app.snapshot_records n WHERE n.owner_id=s.owner_id AND
       n.id=s.id AND n.revision>s.revision)) OR
    app.snapshot_conflict(own,evidence.snapshot_id,evidence.reference_revision) OR EXISTS (
     SELECT 1 FROM app.snapshot_records a JOIN app.staged_rows ar
      ON ar.owner_id=a.owner_id AND ar.id=a.source_row_id
     JOIN app.snapshot_records b ON b.owner_id=a.owner_id AND b.account_id=a.account_id
      AND b.position_id IS NOT DISTINCT FROM a.position_id
      AND b.currency IS NOT DISTINCT FROM a.currency AND b.id<>a.id
      AND b.as_of_date=a.as_of_date AND b.status='active'
     JOIN app.staged_rows br ON br.owner_id=b.owner_id AND br.id=b.source_row_id
     JOIN app.snapshot_components bv ON bv.owner_id=b.owner_id AND bv.snapshot_id=b.id
      AND bv.revision=b.revision AND bv.role=CASE scoped.kind WHEN 'cash' THEN 'net_cash'
        ELSE 'quantity' END
     WHERE a.owner_id=own AND a.id=evidence.snapshot_id AND a.revision=evidence.reference_revision
      AND NOT EXISTS (SELECT 1 FROM app.snapshot_records n WHERE n.owner_id=b.owner_id
       AND n.id=b.id AND n.revision>b.revision)
      AND bv.amount IS DISTINCT FROM evidence.amount AND
       (br.reconciliation_boundary IS NULL OR ar.reconciliation_boundary IS NULL OR
        br.reconciliation_boundary=ar.reconciliation_boundary)) THEN
    RAISE EXCEPTION 'Reconciliation checkpoint is stale or conflicting'; END IF;
  END LOOP;
 END IF;

 FOR metrics IN SELECT side,
   count(*) FILTER (WHERE part='opening') AS openings,
   count(*) FILTER (WHERE part='closing') AS closings,
   min(amount) FILTER (WHERE part='opening') AS opening,
   min(amount) FILTER (WHERE part='closing') AS closing,
   count(*) FILTER (WHERE part='activity' AND posting_state='posted') AS posted,
   count(*) FILTER (WHERE part='activity' AND posting_state='pending') AS pending,
   COALESCE(sum(amount) FILTER (WHERE part='activity' AND posting_state='posted'),0) AS total
  FROM app.completion_inputs WHERE owner_id=own AND scope_id=scope_key GROUP BY side LOOP
  IF metrics.openings<>1 OR metrics.closings<>1 OR
   metrics.opening<>scoped.opening_amount OR metrics.closing<>scoped.closing_amount OR
   metrics.opening+metrics.total<>metrics.closing OR
   (metrics.side='source' AND (metrics.posted,metrics.pending,metrics.total) IS DISTINCT FROM
    (scoped.source_posted_count::bigint,scoped.source_pending_count::bigint,scoped.source_total)) OR
   (metrics.side='combined' AND (metrics.posted,metrics.pending,metrics.total) IS DISTINCT FROM
    (scoped.combined_posted_count::bigint,scoped.combined_pending_count::bigint,scoped.combined_total))
   THEN RAISE EXCEPTION 'Reconciliation equation does not balance'; END IF;
 END LOOP;
END $f$;

CREATE FUNCTION app.check_completion_scope() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
BEGIN
 IF TG_TABLE_NAME='completion_scopes' THEN
  PERFORM app.validate_completion_scope(NEW.owner_id,NEW.id);
 ELSE PERFORM app.validate_completion_scope(NEW.owner_id,NEW.scope_id); END IF;
 RETURN NULL;
END $f$;

"""


def upgrade() -> None:
    op.execute("""
        ALTER TABLE app.completion_receipts DROP CONSTRAINT completion_receipts_mode_check,
            DROP CONSTRAINT completion_receipts_coverage_check,
            ADD CONSTRAINT completion_mode_coverage CHECK (
                (mode='limited' AND coverage IN ('partial_activity','unknown','snapshot')) OR
                (mode='reconciled' AND coverage='complete_activity'))
    """)
    op.execute(CURRENT_GUARD)
    op.execute(TABLE_SQL)
    op.execute(QUERIES)
    op.execute(CHECKS)
    for signature in HELPERS:
        op.execute(f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO trading_runtime")
    for function in ("check_reconciled_receipt", "check_completion_scope"):
        op.execute(f"REVOKE ALL ON FUNCTION app.{function}() FROM PUBLIC")
    columns = (
        "owner_id,id,receipt_id,kind,account_id,position_id,currency,period_start,period_end,"
        "date_basis,rule_version,opening_amount,closing_amount,source_total,combined_total,"
        "source_posted_count,source_pending_count,combined_posted_count,combined_pending_count,"
        "input_count",
        "owner_id,scope_id,side,part,reference_id,reference_revision,source_row_id,event_id,"
        "snapshot_id,source,amount,evidence_date,posting_state",
    )
    for table, fields in zip(TABLES, columns, strict=True):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth")
        op.execute(f"""
            CREATE POLICY reconciliation_owner ON app.{table} TO trading_runtime
            USING (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
            WITH CHECK (owner_id=app.current_owner_id() AND EXISTS (SELECT 1 FROM app.owners
                WHERE id=app.current_owner_id() AND is_active))
        """)
        op.execute(f"GRANT SELECT,INSERT ({fields}) ON app.{table} TO trading_runtime")
        for prefix, function in (
            ("a_serialize_financial_write", "serialize_financial_write"),
            ("b_completion_budget", "guard_completion_budget"),
        ):
            op.execute(
                f"CREATE TRIGGER {prefix} BEFORE INSERT ON app.{table} "
                f"FOR EACH ROW EXECUTE FUNCTION app.{function}()"
            )
        op.execute(
            f"CREATE CONSTRAINT TRIGGER check_completion_scope AFTER INSERT ON app.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "app.check_completion_scope()"
        )
    op.execute(
        "CREATE CONSTRAINT TRIGGER check_reconciled_receipt "
        "AFTER INSERT ON app.completion_receipts "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_reconciled_receipt()"
    )


def downgrade() -> None:
    op.execute("""
        DO $f$ BEGIN
            IF EXISTS (SELECT 1 FROM app.completion_receipts WHERE mode='reconciled') OR
                EXISTS (SELECT 1 FROM app.completion_scopes) OR
                EXISTS (SELECT 1 FROM app.completion_inputs) THEN
                RAISE EXCEPTION 'Reconciliation evidence cannot be downgraded'; END IF;
        END $f$
    """)
    op.execute("DROP TRIGGER check_reconciled_receipt ON app.completion_receipts")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    for function in ("check_completion_scope", "check_reconciled_receipt"):
        op.execute(f"DROP FUNCTION app.{function}()")
    for signature in reversed(HELPERS):
        op.execute(f"DROP FUNCTION app.{signature}")
    op.execute(PREVIOUS_GUARD)
    op.execute("""
        ALTER TABLE app.completion_receipts DROP CONSTRAINT completion_mode_coverage,
            ADD CONSTRAINT completion_receipts_mode_check CHECK (mode='limited'),
            ADD CONSTRAINT completion_receipts_coverage_check CHECK (
                coverage IN ('partial_activity','unknown','snapshot'))
    """)
