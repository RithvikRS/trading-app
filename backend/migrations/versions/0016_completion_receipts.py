"""Atomic receipts for limited source coverage, with immutable reviewed dispositions."""

from alembic import op

revision = "0016_completion_receipts"
down_revision = "0015_completion_baseline"
branch_labels = None
depends_on = None

TABLES = ("completion_receipts", "completion_rows")
CONSUMPTION = (
    "financial_events",
    "lot_observations",
    "snapshot_records",
    "event_evidence_links",
    "completion_rows",
)
HELPERS = (
    "completion_uuid(jsonb)",
    "completion_revision(jsonb,boolean)",
    "completion_canonical(jsonb)",
    "valid_completion_manifest(jsonb)",
    "completion_raw_targets(uuid,uuid)",
)
TRIGGER_FUNCTIONS = (
    "guard_completion_receipt",
    "check_completion_receipt",
    "guard_completion_review",
    "check_completion_consumption",
    "check_completion_row",
    "guard_completion_budget",
)

MANIFEST = """
CREATE FUNCTION app.completion_uuid(value jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog AS $f$
 SELECT (jsonb_typeof(value)='string' AND length(value#>>'{}')=36 AND value#>>'{}' ~
  '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND
  value#>>'{}'<>'00000000-0000-0000-0000-000000000000')
$f$;
CREATE FUNCTION app.completion_revision(value jsonb,initial boolean DEFAULT false) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog AS $f$
 SELECT CASE WHEN jsonb_typeof(value)='number' AND value::text ~ '^(0|[1-9][0-9]{0,15})$'
  THEN value::text::bigint BETWEEN CASE WHEN initial THEN 0 ELSE 1 END AND 9007199254740991
  ELSE false END
$f$;
CREATE FUNCTION app.completion_canonical(value jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog AS $f$
DECLARE result text;
BEGIN
 CASE jsonb_typeof(value)
 WHEN 'object' THEN
  SELECT '{'||COALESCE(string_agg(to_jsonb(key)::text||':'||app.completion_canonical(item),','
   ORDER BY key COLLATE "C"),'')||'}' INTO result FROM jsonb_each(value) AS pair(key,item);
 WHEN 'array' THEN
  SELECT '['||COALESCE(string_agg(app.completion_canonical(item),',' ORDER BY n),'')||']'
   INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS element(item,n);
 ELSE result := value::text;
 END CASE;
 RETURN result;
END $f$;
CREATE FUNCTION app.valid_completion_manifest(doc jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog AS $f$
DECLARE r jsonb; s jsonb; anchor jsonb; field text; ids text[] := ARRAY[]::text[];
        selections text[] := ARRAY[]::text[];
BEGIN
 IF jsonb_typeof(doc)<>'object' OR NOT doc ?& ARRAY['request_contract','idempotency_key',
  'batch_id','batch_revision','baseline','mode','rows','selections'] OR
  (doc-ARRAY['request_contract','idempotency_key','batch_id','batch_revision','baseline',
     'mode','rows','selections'])<>'{}'::jsonb THEN RETURN false; END IF;
 IF ((doc->'request_contract')::text='1') IS NOT TRUE
  OR jsonb_typeof(doc->'mode')<>'string' OR doc->>'mode' NOT IN ('limited','reconciled')
  OR jsonb_typeof(doc->'baseline')<>'string' OR length(doc->>'baseline')<>64
  OR doc->>'baseline' !~ '^[0-9a-f]{64}$'
  OR app.completion_uuid(doc->'idempotency_key') IS NOT TRUE
  OR app.completion_uuid(doc->'batch_id') IS NOT TRUE
  OR app.completion_revision(doc->'batch_revision') IS NOT TRUE
  OR jsonb_typeof(doc->'rows')<>'array' OR jsonb_typeof(doc->'selections')<>'array'
  THEN RETURN false; END IF;
 IF jsonb_array_length(doc->'rows') NOT BETWEEN 1 AND 100 OR
  jsonb_array_length(doc->'selections')>100 THEN RETURN false; END IF;
 FOR r IN SELECT value FROM jsonb_array_elements(doc->'rows') LOOP
  IF jsonb_typeof(r)<>'object' OR NOT r ?& ARRAY['row_id','review_revision','operation',
   'provider_reference_supplied'] OR (r-ARRAY['row_id','review_revision','operation',
   'provider_reference_supplied','position_id','lot_id','lot_source_row_id','target_kind',
   'target_id','target_revision','correction_reason'])<>'{}'::jsonb THEN RETURN false; END IF;
  IF app.completion_uuid(r->'row_id') IS NOT TRUE OR
   app.completion_revision(r->'review_revision') IS NOT TRUE OR
   jsonb_typeof(r->'provider_reference_supplied')<>'boolean' OR
   jsonb_typeof(r->'operation')<>'string' OR r->>'operation' NOT IN ('record','correct','exclude')
   OR r->>'row_id'=ANY(ids) THEN RETURN false; END IF;
  ids := array_append(ids,r->>'row_id');
  FOREACH field IN ARRAY ARRAY['position_id','lot_id','lot_source_row_id','target_id'] LOOP
   IF r ? field AND app.completion_uuid(r->field) IS NOT TRUE THEN RETURN false; END IF;
  END LOOP;
  IF (r ? 'lot_id' AND r ? 'lot_source_row_id') OR
   ((r ? 'lot_id' OR r ? 'lot_source_row_id') AND NOT r ? 'position_id') OR
   r->>'lot_source_row_id'=r->>'row_id' THEN RETURN false; END IF;
  IF r->>'operation'='correct' THEN
   IF NOT r ?& ARRAY['target_kind','target_id','target_revision','correction_reason'] OR
    r ?| ARRAY['position_id','lot_id','lot_source_row_id'] OR
    r->'provider_reference_supplied'<>'false'::jsonb OR
    app.completion_revision(r->'target_revision') IS NOT TRUE OR
    jsonb_typeof(r->'target_kind')<>'string' OR r->>'target_kind' NOT IN
    ('event','lot','snapshot') OR
    jsonb_typeof(r->'correction_reason')<>'string' OR r->>'correction_reason' NOT IN
     ('source_correction','posting_update','cancellation','reinstatement') OR
    (r->>'correction_reason'='posting_update' AND r->>'target_kind'<>'event')
    THEN RETURN false; END IF;
  ELSIF r ?| ARRAY['target_kind','target_id','target_revision','correction_reason'] THEN
   RETURN false;
  END IF;
  IF r->>'operation'='exclude' AND (r->'provider_reference_supplied'<>'false'::jsonb OR
   r ?| ARRAY['position_id','lot_id','lot_source_row_id']) THEN RETURN false; END IF;
  IF r ? 'lot_source_row_id' THEN
   SELECT value INTO anchor FROM jsonb_array_elements(doc->'rows')
    WHERE value->>'row_id'=r->>'lot_source_row_id';
   IF NOT FOUND OR anchor->>'operation'<>'record' OR
    anchor ?| ARRAY['lot_id','lot_source_row_id'] THEN RETURN false; END IF;
  END IF;
 END LOOP;
 FOR s IN SELECT value FROM jsonb_array_elements(doc->'selections') LOOP
  IF jsonb_typeof(s)<>'object' OR NOT s ?& ARRAY['row_id','expected_revision','reason'] OR
   (s-ARRAY['row_id','expected_revision','reason'])<>'{}'::jsonb OR
   app.completion_uuid(s->'row_id') IS NOT TRUE OR
   app.completion_revision(s->'expected_revision',true) IS NOT TRUE OR
   jsonb_typeof(s->'reason')<>'string' OR s->>'reason' NOT IN
    ('reviewed','newer_evidence','correction')
   OR s->>'row_id'=ANY(selections) OR NOT s->>'row_id'=ANY(ids) THEN RETURN false; END IF;
  selections := array_append(selections,s->>'row_id');
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(doc->'rows') WHERE value->>'row_id'=s->>'row_id'
   AND value->>'operation'='exclude') THEN RETURN false; END IF;
 END LOOP;
 IF ids IS DISTINCT FROM ARRAY(SELECT unnest(ids) ORDER BY 1) OR
  selections IS DISTINCT FROM ARRAY(SELECT unnest(selections) ORDER BY 1) THEN RETURN false; END IF;
 RETURN true;
END $f$;
"""

TABLE_SQL = """
CREATE TABLE app.completion_receipts (
    owner_id uuid NOT NULL,
    id uuid NOT NULL CHECK (id <> '00000000-0000-0000-0000-000000000000'),
    idempotency_key uuid NOT NULL CHECK (idempotency_key <> '00000000-0000-0000-0000-000000000000'),
    batch_id uuid NOT NULL,
    batch_revision bigint NOT NULL CHECK (batch_revision BETWEEN 1 AND 9007199254740991),
    baseline_digest text NOT NULL CHECK (baseline_digest ~ '^[0-9a-f]{64}$'),
    request_canonical text NOT NULL CHECK (octet_length(request_canonical) BETWEEN 2 AND 65536),
    request_digest text NOT NULL CHECK (request_digest =
    encode(sha256(convert_to(request_canonical,'UTF8')),'hex')),
    mode text NOT NULL CHECK (mode='limited'),
    coverage text NOT NULL CHECK (coverage IN ('partial_activity','unknown','snapshot')),
    row_count integer NOT NULL CHECK (row_count BETWEEN 1 AND 100),
    selection_count integer NOT NULL CHECK (selection_count BETWEEN 0 AND 100),
    created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    PRIMARY KEY (owner_id,id),
    UNIQUE (owner_id,idempotency_key),
    UNIQUE (owner_id,batch_id),
    FOREIGN KEY (owner_id,batch_id) REFERENCES app.import_batches(owner_id,id)
);

CREATE TABLE app.completion_rows (
    owner_id uuid NOT NULL, receipt_id uuid NOT NULL, source_row_id uuid NOT NULL,
    review_revision bigint NOT NULL,
    operation text NOT NULL CHECK (operation IN ('record','correct','exclude')),
    outcome text NOT NULL CHECK (outcome IN ('recorded','linked','corrected','excluded')),
    event_id uuid, lot_observation_id uuid, snapshot_id uuid, record_revision bigint,
    provider_identity_id uuid, selection_id uuid, selection_revision bigint,
    PRIMARY KEY (owner_id,source_row_id),
    FOREIGN KEY (owner_id,receipt_id) REFERENCES app.completion_receipts(owner_id,id),
    FOREIGN KEY (owner_id,source_row_id,review_revision) REFERENCES
    app.review_decisions(owner_id,row_id,revision),
    FOREIGN KEY (owner_id,event_id,record_revision) REFERENCES
    app.financial_events(owner_id,id,revision),
    FOREIGN KEY (owner_id,lot_observation_id,record_revision) REFERENCES
    app.lot_observations(owner_id,id,revision),
    FOREIGN KEY (owner_id,snapshot_id,record_revision) REFERENCES
    app.snapshot_records(owner_id,id,revision),
    FOREIGN KEY (owner_id,provider_identity_id) REFERENCES
    app.event_provider_identities(owner_id,id),
    FOREIGN KEY (owner_id,selection_id,selection_revision) REFERENCES
    app.snapshot_selections(owner_id,id,revision),
    CHECK ((operation='exclude' AND outcome='excluded' AND
            num_nonnulls(event_id,lot_observation_id,snapshot_id,record_revision,provider_identity_id,selection_id,selection_revision)=0)
        OR (operation IN ('record','correct') AND record_revision IS NOT NULL AND
            record_revision BETWEEN 1 AND 9007199254740991 AND
            num_nonnulls(event_id,lot_observation_id,snapshot_id)=1 AND
            ((operation='record' AND outcome IN ('recorded','linked')) OR
             (operation='correct' AND outcome='corrected')))),
    CHECK (provider_identity_id IS NULL OR (event_id IS NOT NULL AND operation='record')),
    CHECK ((selection_id IS NULL AND selection_revision IS NULL) OR
        (selection_id IS NOT NULL AND selection_revision IS NOT NULL AND snapshot_id IS NOT NULL))
);

"""

GUARDS = """
ALTER FUNCTION app.financial_baseline() RENAME TO financial_baseline_v1;
CREATE FUNCTION app.financial_baseline() RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path=pg_catalog AS $f$
DECLARE previous text; total bigint; receipts jsonb;
BEGIN
 previous := app.financial_baseline_v1();
 SELECT count(*),COALESCE(jsonb_agg(id ORDER BY id),'[]'::jsonb) INTO total,receipts
  FROM (SELECT id FROM app.completion_receipts WHERE owner_id=app.current_owner_id()
        ORDER BY id LIMIT 1001) bounded;
 IF total>1000 THEN RAISE EXCEPTION 'Completion state exceeds its bounded scope'; END IF;
 RETURN encode(sha256(convert_to(jsonb_build_object('baseline_contract',2,'previous',previous,
  'receipts',receipts)::text,'UTF8')),'hex');
END $f$;

CREATE FUNCTION app.guard_completion_receipt() RETURNS trigger
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

CREATE FUNCTION app.check_completion_receipt() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
DECLARE receipt app.completion_receipts%ROWTYPE; receipt_key uuid;
BEGIN
 IF TG_TABLE_NAME='completion_receipts' THEN receipt_key := NEW.id; ELSE receipt_key :=
    NEW.receipt_id; END IF;
 SELECT * INTO receipt FROM app.completion_receipts WHERE owner_id=NEW.owner_id AND id=receipt_key;
 IF NOT FOUND OR (SELECT count(*) FROM app.completion_rows WHERE owner_id=receipt.owner_id
   AND receipt_id=receipt.id)<>receipt.row_count OR
  (SELECT count(*) FROM app.staged_rows WHERE owner_id=receipt.owner_id AND
   batch_id=receipt.batch_id)<>receipt.row_count OR
  (SELECT count(*) FROM app.completion_rows WHERE owner_id=receipt.owner_id
   AND receipt_id=receipt.id AND selection_id IS NOT NULL)<>receipt.selection_count THEN
  RAISE EXCEPTION 'Completion receipt is incomplete'; END IF;
 IF current_user='trading_runtime' AND EXISTS (
  SELECT 1 FROM app.import_batches b WHERE b.owner_id=receipt.owner_id AND b.id=receipt.batch_id AND
   (EXISTS (SELECT 1 FROM app.import_batches newer WHERE newer.owner_id=b.owner_id AND
     newer.observation_id=b.observation_id AND newer.revision>b.revision) OR
    EXISTS (SELECT 1 FROM app.source_observations newer WHERE newer.owner_id=b.owner_id AND
     newer.previous_id=b.observation_id))) THEN
  RAISE EXCEPTION 'Completed batch is stale'; END IF;
 -- Every row validator also checks unique manifest membership and batch membership.
 RETURN NULL;
END $f$;

CREATE FUNCTION app.guard_completion_review() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
BEGIN
 IF current_user='trading_runtime' AND EXISTS (SELECT 1 FROM app.completion_rows
  WHERE owner_id=NEW.owner_id AND source_row_id=NEW.row_id) THEN
  RAISE EXCEPTION 'Completed source review is immutable'; END IF;
 RETURN NEW;
END $f$;

CREATE FUNCTION app.check_completion_consumption() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
DECLARE used app.completion_rows%ROWTYPE;
BEGIN
 SELECT * INTO used FROM app.completion_rows WHERE owner_id=NEW.owner_id
  AND source_row_id=NEW.source_row_id;
 IF FOUND AND (
  EXISTS (SELECT 1 FROM app.financial_events WHERE owner_id=used.owner_id AND
   source_row_id=used.source_row_id AND (id,revision) IS DISTINCT FROM
    (used.event_id,used.record_revision)) OR
  EXISTS (SELECT 1 FROM app.lot_observations WHERE owner_id=used.owner_id AND
   source_row_id=used.source_row_id AND (id,revision) IS DISTINCT FROM
    (used.lot_observation_id,used.record_revision)) OR
  EXISTS (SELECT 1 FROM app.snapshot_records WHERE owner_id=used.owner_id AND
   source_row_id=used.source_row_id AND (id,revision) IS DISTINCT FROM
    (used.snapshot_id,used.record_revision)) OR
  EXISTS (SELECT 1 FROM app.event_evidence_links WHERE owner_id=used.owner_id AND
   source_row_id=used.source_row_id AND (event_id,event_revision) IS DISTINCT FROM
    (used.event_id,used.record_revision))
 ) THEN RAISE EXCEPTION 'Completed source occurrence already has a disposition'; END IF;
 RETURN NULL;
END $f$;

"""

ROWS = """
CREATE FUNCTION app.completion_raw_targets(own uuid,row_key uuid)
RETURNS TABLE(kind text,id uuid)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=pg_catalog AS $f$
 WITH raw_rows AS (
  SELECT r.id FROM app.staged_rows s JOIN app.import_batches b
   ON b.owner_id=s.owner_id AND b.id=s.batch_id JOIN app.import_batches other
   ON other.owner_id=b.owner_id AND other.observation_id=b.observation_id
   JOIN app.staged_rows r ON r.owner_id=other.owner_id AND r.batch_id=other.id
    AND r.occurrence=s.occurrence
  WHERE s.owner_id=own AND s.id=row_key AND r.id<>row_key
 )
 SELECT 'event',e.id FROM app.financial_events e WHERE e.owner_id=own AND e.source_row_id IN
    (SELECT id FROM raw_rows)
 UNION SELECT 'lot',e.id FROM app.lot_observations e WHERE e.owner_id=own AND e.source_row_id IN
    (SELECT id FROM raw_rows)
 UNION SELECT 'snapshot',e.id FROM app.snapshot_records e WHERE e.owner_id=own AND
    e.source_row_id IN (SELECT id FROM raw_rows)
 UNION SELECT 'event',e.event_id FROM app.event_evidence_links e WHERE e.owner_id=own AND
    e.source_row_id IN (SELECT id FROM raw_rows)
$f$;

CREATE FUNCTION app.check_completion_row() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
DECLARE receipt app.completion_receipts%ROWTYPE; source app.staged_rows%ROWTYPE;
 review app.review_decisions%ROWTYPE; directive jsonb; choice jsonb; target record;
 family text; chosen app.snapshot_selections%ROWTYPE;
BEGIN
 SELECT * INTO receipt FROM app.completion_receipts WHERE owner_id=NEW.owner_id AND
    id=NEW.receipt_id;
 SELECT * INTO source FROM app.staged_rows WHERE owner_id=NEW.owner_id AND id=NEW.source_row_id;
 SELECT * INTO review FROM app.review_decisions WHERE owner_id=NEW.owner_id AND
  row_id=NEW.source_row_id AND revision=NEW.review_revision;
 SELECT value INTO directive FROM jsonb_array_elements(receipt.request_canonical::jsonb->'rows')
  WHERE value->>'row_id'=NEW.source_row_id::text;
 IF receipt.id IS NULL OR source.id IS NULL OR review.row_id IS NULL OR directive IS NULL OR
  source.batch_id<>receipt.batch_id OR directive->>'operation'<>NEW.operation OR
  (directive->>'review_revision')::bigint<>NEW.review_revision OR
  (NEW.operation='exclude' AND review.action<>'exclude') OR
  (NEW.operation<>'exclude' AND review.action<>'include') THEN
  RAISE EXCEPTION 'Completed row does not match its reviewed source'; END IF;
 IF current_user='trading_runtime' AND EXISTS (SELECT 1 FROM app.review_decisions WHERE
  owner_id=NEW.owner_id AND row_id=NEW.source_row_id AND revision>NEW.review_revision) THEN
  RAISE EXCEPTION 'Completed row review is stale'; END IF;
 IF NEW.operation='exclude' THEN RETURN NULL; END IF;
 IF NEW.event_id IS NOT NULL THEN
  family := 'event';
  SELECT e.*,NULL::uuid AS lot_id INTO target FROM app.financial_events e
   WHERE owner_id=NEW.owner_id AND id=NEW.event_id AND revision=NEW.record_revision;
  IF receipt.coverage='snapshot' THEN RAISE EXCEPTION 'Snapshot coverage cannot post activity';
    END IF;
 ELSIF NEW.lot_observation_id IS NOT NULL THEN
  family := 'lot';
  SELECT e.*,l.position_id,p.account_id,p.instrument_id INTO target FROM app.lot_observations e
   JOIN app.lots l ON l.owner_id=e.owner_id AND l.id=e.lot_id
   JOIN app.account_positions p ON p.owner_id=l.owner_id AND p.id=l.position_id
   WHERE e.owner_id=NEW.owner_id AND e.id=NEW.lot_observation_id AND e.revision=NEW.record_revision;
 ELSE
  family := 'snapshot';
  SELECT e.*,NULL::uuid AS lot_id INTO target FROM app.snapshot_records e
   WHERE owner_id=NEW.owner_id AND id=NEW.snapshot_id AND revision=NEW.record_revision;
 END IF;
 IF NOT FOUND THEN RAISE EXCEPTION 'Completed row target is unavailable'; END IF;
 PERFORM app.check_record_review(NEW.owner_id,NEW.source_row_id,NEW.review_revision,
  target.account_id,target.instrument_id,source.kind='cancellation');
 IF EXISTS (SELECT 1 FROM app.completion_raw_targets(NEW.owner_id,NEW.source_row_id) raw
  WHERE (raw.kind,raw.id) IS DISTINCT FROM (family,target.id)) THEN
  RAISE EXCEPTION 'Raw occurrence already has a different economic target'; END IF;
 IF NEW.operation='correct' THEN
  IF directive->>'target_kind'<>family OR (directive->>'target_id')::uuid<>target.id OR
   (directive->>'target_revision')::bigint+1<>target.revision OR
   directive->>'correction_reason' IS DISTINCT FROM target.correction_reason OR
   target.source_row_id<>NEW.source_row_id OR target.source_review_revision<>NEW.review_revision
    THEN
   RAISE EXCEPTION 'Completed correction differs from its explicit request'; END IF;
 ELSE
  IF target.status<>'active' OR target.position_id IS DISTINCT FROM
   (directive->>'position_id')::uuid THEN RAISE EXCEPTION 'Completed record scope differs'; END IF;
  IF target.source_row_id=NEW.source_row_id THEN
   IF target.revision<>1 OR target.source_review_revision<>NEW.review_revision OR
    NEW.outcome<>'recorded' THEN RAISE EXCEPTION 'Completed primary record differs'; END IF;
  ELSE
   IF family<>'event' OR NEW.outcome<>'linked' THEN
    RAISE EXCEPTION 'Reused evidence requires a proven event identity'; END IF;
   IF NOT EXISTS (SELECT 1 FROM app.completion_raw_targets(NEW.owner_id,NEW.source_row_id)
     WHERE kind='event' AND id=target.id) AND NOT EXISTS (
      SELECT 1 FROM app.event_evidence_links WHERE owner_id=NEW.owner_id AND
       source_row_id=NEW.source_row_id AND event_id=target.id AND
       event_revision=target.revision AND review_revision=NEW.review_revision) THEN
    RAISE EXCEPTION 'Reused event identity is unavailable'; END IF;
   IF (source.kind,source.posting_state,source.trade_date,source.settlement_date,
       source.booking_date,source.value_date) IS DISTINCT FROM
      (target.kind,target.posting_state,target.trade_date,target.settlement_date,
       target.booking_date,target.value_date) OR
    EXISTS ((SELECT role,amount,currency,missing_reason FROM app.staged_values WHERE
      owner_id=NEW.owner_id AND row_id=NEW.source_row_id) EXCEPT
     (SELECT role,amount,currency,missing_reason FROM app.event_components WHERE
      owner_id=NEW.owner_id AND event_id=target.id AND revision=target.revision)) OR
    EXISTS ((SELECT role,amount,currency,missing_reason FROM app.event_components WHERE
      owner_id=NEW.owner_id AND event_id=target.id AND revision=target.revision) EXCEPT
     (SELECT role,amount,currency,missing_reason FROM app.staged_values WHERE
      owner_id=NEW.owner_id AND row_id=NEW.source_row_id)) THEN
    RAISE EXCEPTION 'Reused event economics differ'; END IF;
  END IF;
  IF family<>'lot' AND directive ?| ARRAY['lot_id','lot_source_row_id'] THEN
   RAISE EXCEPTION 'Only lot observations accept lot targets'; END IF;
  IF directive ? 'lot_id' AND (directive->>'lot_id')::uuid<>target.lot_id THEN
   RAISE EXCEPTION 'Completed lot target differs'; END IF;
  IF directive ? 'lot_source_row_id' AND NOT EXISTS (
   SELECT 1 FROM app.completion_rows cr JOIN app.lot_observations lo ON
    lo.owner_id=cr.owner_id AND lo.id=cr.lot_observation_id AND lo.revision=cr.record_revision
    JOIN app.staged_rows sr ON sr.owner_id=cr.owner_id AND sr.id=cr.source_row_id
   WHERE cr.owner_id=NEW.owner_id AND cr.receipt_id=NEW.receipt_id AND
    cr.source_row_id=(directive->>'lot_source_row_id')::uuid AND cr.operation='record' AND
    lo.scope='lot_acquisition' AND lo.status='active' AND lo.lot_id=target.lot_id AND
    sr.occurrence<source.occurrence) THEN RAISE EXCEPTION 'New lot anchor is unavailable'; END IF;
  IF current_user='trading_runtime' AND family<>'event' AND EXISTS (
    SELECT 1 FROM app.completion_raw_targets(NEW.owner_id,NEW.source_row_id)) THEN
   RAISE EXCEPTION 'Repeated lot or snapshot occurrence requires correction'; END IF;
 END IF;
 IF (directive->>'provider_reference_supplied')::boolean THEN
  IF NEW.provider_identity_id IS NULL OR NOT EXISTS (SELECT 1 FROM app.event_evidence_links
   WHERE owner_id=NEW.owner_id AND source_row_id=NEW.source_row_id AND
    identity_id=NEW.provider_identity_id AND event_id=NEW.event_id AND
    event_revision=NEW.record_revision AND review_revision=NEW.review_revision) THEN
   RAISE EXCEPTION 'Completed provider identity is unavailable'; END IF;
 ELSIF NEW.provider_identity_id IS NOT NULL THEN
  RAISE EXCEPTION 'Completed provider identity was not requested';
 END IF;
 SELECT value INTO choice FROM jsonb_array_elements(receipt.request_canonical::jsonb->'selections')
  WHERE value->>'row_id'=NEW.source_row_id::text;
 IF choice IS NULL THEN
  IF NEW.selection_id IS NOT NULL THEN RAISE EXCEPTION 'Snapshot selection was not requested';
    END IF;
 ELSE
  SELECT * INTO chosen FROM app.snapshot_selections WHERE owner_id=NEW.owner_id AND
   id=NEW.selection_id AND revision=NEW.selection_revision;
  IF NOT FOUND OR (chosen.snapshot_id,chosen.snapshot_revision,chosen.reason,chosen.revision)
   IS DISTINCT FROM (NEW.snapshot_id,NEW.record_revision,choice->>'reason',
    (choice->>'expected_revision')::bigint+1) THEN
   RAISE EXCEPTION 'Completed selection differs from its request'; END IF;
  IF current_user='trading_runtime' AND EXISTS (SELECT 1 FROM app.snapshot_selections WHERE
   owner_id=NEW.owner_id AND id=chosen.id AND revision>chosen.revision) THEN
   RAISE EXCEPTION 'Completed snapshot selection is stale'; END IF;
 END IF;
 IF current_user='trading_runtime' AND (
  EXISTS (SELECT 1 FROM app.financial_events WHERE owner_id=NEW.owner_id AND
   id=NEW.event_id AND revision>NEW.record_revision) OR
  EXISTS (SELECT 1 FROM app.lot_observations WHERE owner_id=NEW.owner_id AND
   id=NEW.lot_observation_id AND revision>NEW.record_revision) OR
  EXISTS (SELECT 1 FROM app.snapshot_records WHERE owner_id=NEW.owner_id AND
   id=NEW.snapshot_id AND revision>NEW.record_revision)) THEN
  RAISE EXCEPTION 'Completed financial target is stale'; END IF;
 RETURN NULL;
END $f$;
"""


def upgrade() -> None:
    op.execute(MANIFEST)
    op.execute(TABLE_SQL)
    op.execute(GUARDS)
    op.execute(ROWS)
    op.execute("""
        CREATE FUNCTION app.guard_completion_budget() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $f$
        DECLARE total bigint;
        BEGIN
            IF current_user='trading_runtime' THEN
                EXECUTE format('SELECT count(*) FROM app.%I WHERE owner_id=$1',TG_TABLE_NAME)
                    INTO total USING NEW.owner_id;
                IF total>=1000 THEN RAISE EXCEPTION 'Completion record limit reached'; END IF;
            END IF;
            RETURN NEW;
        END $f$
    """)
    op.execute(
        "CREATE INDEX completion_rows_receipt ON "
        "app.completion_rows(owner_id,receipt_id,source_row_id)"
    )
    for signature in (*HELPERS, "financial_baseline()"):
        op.execute(f"REVOKE ALL ON FUNCTION app.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION app.{signature} TO trading_runtime")
    for function in TRIGGER_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION app.{function}() FROM PUBLIC")
    columns = (
        "owner_id,id,idempotency_key,batch_id,batch_revision,baseline_digest,request_canonical,"
        "request_digest,mode,coverage,row_count,selection_count",
        "owner_id,receipt_id,source_row_id,review_revision,operation,outcome,event_id,"
        "lot_observation_id,snapshot_id,record_revision,provider_identity_id,selection_id,"
        "selection_revision",
    )
    for table, fields in zip(TABLES, columns, strict=True):
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE app.{table} FORCE ROW LEVEL SECURITY")
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC,trading_runtime,trading_auth")
        op.execute(f"""
            CREATE POLICY completion_owner ON app.{table} TO trading_runtime
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
                f"CREATE TRIGGER {prefix} BEFORE INSERT ON app.{table} FOR EACH ROW "
                f"EXECUTE FUNCTION app.{function}()"
            )
        op.execute(
            f"CREATE CONSTRAINT TRIGGER check_completion_receipt AFTER INSERT ON app.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "app.check_completion_receipt()"
        )
    op.execute(
        "CREATE TRIGGER c_completion_receipt BEFORE INSERT ON app.completion_receipts "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_completion_receipt()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER check_completion_row AFTER INSERT ON app.completion_rows "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.check_completion_row()"
    )
    op.execute(
        "CREATE TRIGGER guard_completion_review BEFORE INSERT ON app.review_decisions "
        "FOR EACH ROW EXECUTE FUNCTION app.guard_completion_review()"
    )
    for table in CONSUMPTION:
        op.execute(
            f"CREATE CONSTRAINT TRIGGER check_completion_consumption AFTER INSERT ON app.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "app.check_completion_consumption()"
        )


def downgrade() -> None:
    op.execute("""
        DO $f$ BEGIN
            IF EXISTS (SELECT 1 FROM app.completion_receipts) OR
                EXISTS (SELECT 1 FROM app.completion_rows) THEN
                RAISE EXCEPTION 'Completion receipts cannot be downgraded'; END IF;
        END $f$
    """)
    op.execute("DROP TRIGGER guard_completion_review ON app.review_decisions")
    for table in CONSUMPTION:
        op.execute(f"DROP TRIGGER check_completion_consumption ON app.{table}")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    for function in TRIGGER_FUNCTIONS:
        op.execute(f"DROP FUNCTION app.{function}()")
    for signature in reversed(HELPERS):
        op.execute(f"DROP FUNCTION app.{signature}")
    op.execute("DROP FUNCTION app.financial_baseline()")
    op.execute("ALTER FUNCTION app.financial_baseline_v1() RENAME TO financial_baseline")
