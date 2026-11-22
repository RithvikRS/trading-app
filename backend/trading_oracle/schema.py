"""Fixed reviewed DDL; no caller-supplied identifiers or arbitrary migration text."""

import hashlib
import re
from dataclasses import dataclass

SCHEMA = "TRADING_MIGRATOR"
CONTEXT = "TRADING_OWNER_CTX"
FORMAT = 1
LOCK_ID = 84192022


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    size: int | None = None
    default: str | None = None
    nullable: bool = False


@dataclass(frozen=True)
class Constraint:
    name: str
    kind: str
    columns: tuple[str, ...]
    expression: str | None = None
    parent: str | None = None


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    constraints: tuple[Constraint, ...]


@dataclass(frozen=True)
class Grant:
    grantee: str
    object: str
    privilege: str
    columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    key: str
    sql: str
    kind: str
    name: str
    table: Table | None = None
    grant: Grant | None = None

    @property
    def checksum(self) -> str:
        return hashlib.sha256(("oa2.2/v1/" + self.key + "\n" + self.sql).encode()).hexdigest()


def normalize_sql(value: str) -> str:
    """Normalize dictionary whitespace/case, preserving every string literal byte."""
    tokens = re.findall(r"'(?:[^']|'')*'|\"[A-Z][A-Z0-9_]*\"|[A-Za-z_][A-Za-z0-9_$#]*|\S", value)
    return " ".join(
        token if token.startswith("'") else token.strip('"').upper() for token in tokens
    )


OWNER_TABLE = Table(
    "OWNERS",
    (
        Column("ID", "RAW", 16),
        Column("IS_ACTIVE", "NUMBER", default="0"),
        Column("CREATED_AT", "TIMESTAMP(6) WITH TIME ZONE", default="SYSTIMESTAMP"),
    ),
    (
        Constraint("OWNERS_ID_NN", "C", ("ID",), '"ID" IS NOT NULL'),
        Constraint("OWNERS_ACTIVE_NN", "C", ("IS_ACTIVE",), '"IS_ACTIVE" IS NOT NULL'),
        Constraint("OWNERS_CREATED_NN", "C", ("CREATED_AT",), '"CREATED_AT" IS NOT NULL'),
        Constraint("OWNERS_PK", "P", ("ID",)),
        Constraint(
            "OWNERS_ID_EXACT",
            "C",
            ("ID",),
            "VSIZE(id)=16 AND id<>HEXTORAW('00000000000000000000000000000000')",
        ),
        Constraint("OWNERS_ACTIVE_EXACT", "C", ("IS_ACTIVE",), "is_active IN (0,1)"),
    ),
)

IDENTITY_TABLE = Table(
    "OWNER_IDENTITIES",
    (Column("ISSUER", "RAW", 512), Column("SUBJECT", "RAW", 256), Column("OWNER_ID", "RAW", 16)),
    (
        Constraint("IDENTITY_ISSUER_NN", "C", ("ISSUER",), '"ISSUER" IS NOT NULL'),
        Constraint("IDENTITY_SUBJECT_NN", "C", ("SUBJECT",), '"SUBJECT" IS NOT NULL'),
        Constraint("IDENTITY_OWNER_NN", "C", ("OWNER_ID",), '"OWNER_ID" IS NOT NULL'),
        Constraint("IDENTITY_PK", "P", ("ISSUER", "SUBJECT")),
        Constraint("IDENTITY_OWNER_FK", "R", ("OWNER_ID",), parent="OWNERS_PK"),
        Constraint("IDENTITY_ISSUER_SIZE", "C", ("ISSUER",), "VSIZE(issuer) BETWEEN 1 AND 512"),
        Constraint("IDENTITY_SUBJECT_SIZE", "C", ("SUBJECT",), "VSIZE(subject) BETWEEN 1 AND 256"),
    ),
)

PREFERENCE_TABLE = Table(
    "WORKSPACE_PREFERENCES",
    (
        Column("OWNER_ID", "RAW", 16),
        Column("THEME", "VARCHAR2", 5),
        Column("DISPLAY_CURRENCY", "VARCHAR2", 3),
        Column("AMOUNT_MASKED", "NUMBER"),
        Column("REVISION", "NUMBER"),
        Column("CREATED_AT", "TIMESTAMP(6) WITH TIME ZONE"),
        Column("UPDATED_AT", "TIMESTAMP(6) WITH TIME ZONE"),
    ),
    tuple(
        Constraint("PREF_" + suffix + "_NN", "C", (name,), f'"{name}" IS NOT NULL')
        for suffix, name in (
            ("OWNER", "OWNER_ID"),
            ("THEME", "THEME"),
            ("CURRENCY", "DISPLAY_CURRENCY"),
            ("MASKED", "AMOUNT_MASKED"),
            ("REVISION", "REVISION"),
            ("CREATED", "CREATED_AT"),
            ("UPDATED", "UPDATED_AT"),
        )
    )
    + (
        Constraint("PREFERENCES_PK", "P", ("OWNER_ID",)),
        Constraint("PREFERENCES_OWNER_FK", "R", ("OWNER_ID",), parent="OWNERS_PK"),
        Constraint("PREF_THEME_EXACT", "C", ("THEME",), "theme IN ('light','dark')"),
        Constraint(
            "PREF_CURRENCY_EXACT", "C", ("DISPLAY_CURRENCY",), "display_currency IN ('INR','USD')"
        ),
        Constraint("PREF_MASKED_EXACT", "C", ("AMOUNT_MASKED",), "amount_masked IN (0,1)"),
        Constraint(
            "PREF_REVISION_EXACT",
            "C",
            ("REVISION",),
            "revision=TRUNC(revision) AND revision BETWEEN 1 AND 9007199254740991",
        ),
    ),
)

OWNERS = """CREATE TABLE owners (
 id RAW(16) CONSTRAINT owners_id_nn NOT NULL,
 is_active NUMBER DEFAULT 0 CONSTRAINT owners_active_nn NOT NULL,
 created_at TIMESTAMP(6) WITH TIME ZONE DEFAULT SYSTIMESTAMP CONSTRAINT owners_created_nn NOT NULL,
 CONSTRAINT owners_pk PRIMARY KEY(id),
 CONSTRAINT owners_id_exact CHECK(VSIZE(id)=16 AND
  id<>HEXTORAW('00000000000000000000000000000000')),
 CONSTRAINT owners_active_exact CHECK(is_active IN (0,1))
)"""

IDENTITIES = """CREATE TABLE owner_identities (
 issuer RAW(512) CONSTRAINT identity_issuer_nn NOT NULL,
 subject RAW(256) CONSTRAINT identity_subject_nn NOT NULL,
 owner_id RAW(16) CONSTRAINT identity_owner_nn NOT NULL,
 CONSTRAINT identity_pk PRIMARY KEY(issuer,subject),
 CONSTRAINT identity_owner_fk FOREIGN KEY(owner_id) REFERENCES owners(id),
 CONSTRAINT identity_issuer_size CHECK(VSIZE(issuer) BETWEEN 1 AND 512),
 CONSTRAINT identity_subject_size CHECK(VSIZE(subject) BETWEEN 1 AND 256)
)"""

PREFERENCES = """CREATE TABLE workspace_preferences (
 owner_id RAW(16) CONSTRAINT pref_owner_nn NOT NULL,
 theme VARCHAR2(5 BYTE) CONSTRAINT pref_theme_nn NOT NULL,
 display_currency VARCHAR2(3 BYTE) CONSTRAINT pref_currency_nn NOT NULL,
 amount_masked NUMBER CONSTRAINT pref_masked_nn NOT NULL,
 revision NUMBER CONSTRAINT pref_revision_nn NOT NULL,
 created_at TIMESTAMP(6) WITH TIME ZONE CONSTRAINT pref_created_nn NOT NULL,
 updated_at TIMESTAMP(6) WITH TIME ZONE CONSTRAINT pref_updated_nn NOT NULL,
 CONSTRAINT preferences_pk PRIMARY KEY(owner_id),
 CONSTRAINT preferences_owner_fk FOREIGN KEY(owner_id) REFERENCES owners(id),
 CONSTRAINT pref_theme_exact CHECK(theme IN ('light','dark')),
 CONSTRAINT pref_currency_exact CHECK(display_currency IN ('INR','USD')),
 CONSTRAINT pref_masked_exact CHECK(amount_masked IN (0,1)),
 CONSTRAINT pref_revision_exact CHECK(revision=TRUNC(revision) AND
  revision BETWEEN 1 AND 9007199254740991)
)"""

CONTEXT_SPEC = """CREATE OR REPLACE PACKAGE owner_context AUTHID DEFINER AS
 PROCEDURE enter_owner(p_owner IN VARCHAR2);
 PROCEDURE clear_owner;
END owner_context;"""

CONTEXT_BODY = """CREATE OR REPLACE PACKAGE BODY owner_context AS
 PROCEDURE clear_owner IS
 BEGIN
  IF SYS_CONTEXT('USERENV','SESSION_USER') <> 'TRADING_RUNTIME' THEN
   RAISE_APPLICATION_ERROR(-20001,'Workspace access denied.');
  END IF;
  SYS.DBMS_SESSION.CLEAR_CONTEXT('TRADING_OWNER_CTX',NULL,'OWNER_ID');
 END clear_owner;
 PROCEDURE enter_owner(p_owner IN VARCHAR2) IS
  v_id RAW(16);
 BEGIN
  clear_owner;
  IF p_owner IS NULL OR LENGTHB(p_owner) <> 36 OR
   NOT REGEXP_LIKE(p_owner,'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$','c') OR
   p_owner='00000000-0000-0000-0000-000000000000' THEN
   RAISE_APPLICATION_ERROR(-20001,'Workspace access denied.');
  END IF;
  SYS.DBMS_SESSION.SET_CONTEXT('TRADING_OWNER_CTX','OWNER_ID',REPLACE(p_owner,'-',''));
  SELECT id INTO v_id FROM owners WHERE id=HEXTORAW(REPLACE(p_owner,'-','')) AND is_active=1;
 EXCEPTION WHEN OTHERS THEN
  SYS.DBMS_SESSION.CLEAR_CONTEXT('TRADING_OWNER_CTX',NULL,'OWNER_ID');
  RAISE_APPLICATION_ERROR(-20001,'Workspace access denied.');
 END enter_owner;
END owner_context;"""

OWNER_FILTER = """CREATE OR REPLACE FUNCTION owner_filter(p_schema VARCHAR2,p_object VARCHAR2)
 RETURN VARCHAR2 AUTHID DEFINER IS v_owner VARCHAR2(256);
BEGIN
 IF SYS_CONTEXT('USERENV','SESSION_USER') IN ('TRADING_MIGRATOR','TRADING_AUTH') THEN
  RETURN '1=1'; END IF;
 IF SYS_CONTEXT('USERENV','SESSION_USER') <> 'TRADING_RUNTIME' THEN RETURN '1=0'; END IF;
 v_owner:=SYS_CONTEXT('TRADING_OWNER_CTX','OWNER_ID');
 IF v_owner IS NULL OR LENGTHB(v_owner)<>32 OR
  NOT REGEXP_LIKE(v_owner,'^[0-9a-f]{32}$','c') THEN RETURN '1=0'; END IF;
 RETURN 'id=HEXTORAW(SYS_CONTEXT(''TRADING_OWNER_CTX'',''OWNER_ID'')) AND is_active=1';
END;"""

PREFERENCE_FILTER = """CREATE OR REPLACE FUNCTION preference_filter(
 p_schema VARCHAR2,p_object VARCHAR2)
 RETURN VARCHAR2 AUTHID DEFINER IS v_owner VARCHAR2(256);
BEGIN
 IF SYS_CONTEXT('USERENV','SESSION_USER')='TRADING_MIGRATOR' THEN RETURN '1=1'; END IF;
 IF SYS_CONTEXT('USERENV','SESSION_USER')<>'TRADING_RUNTIME' THEN RETURN '1=0'; END IF;
 v_owner:=SYS_CONTEXT('TRADING_OWNER_CTX','OWNER_ID');
 IF v_owner IS NULL OR LENGTHB(v_owner)<>32 OR
  NOT REGEXP_LIKE(v_owner,'^[0-9a-f]{32}$','c') THEN RETURN '1=0'; END IF;
 RETURN 'owner_id=HEXTORAW(SYS_CONTEXT(''TRADING_OWNER_CTX'',''OWNER_ID''))' ||
  ' AND EXISTS (SELECT 1 FROM TRADING_MIGRATOR.owners o' ||
  ' WHERE o.id=owner_id AND o.is_active=1)';
END;"""

IDENTITY_SPEC = """CREATE OR REPLACE PACKAGE identity_lookup AUTHID DEFINER AS
 PROCEDURE resolve_owner(p_issuer IN RAW,p_subject IN RAW,p_owner OUT RAW);
END identity_lookup;"""

IDENTITY_BODY = """CREATE OR REPLACE PACKAGE BODY identity_lookup AS
 PROCEDURE resolve_owner(p_issuer IN RAW,p_subject IN RAW,p_owner OUT RAW) IS
 BEGIN
  p_owner:=NULL;
  IF SYS_CONTEXT('USERENV','SESSION_USER')<>'TRADING_AUTH' OR
   p_issuer IS NULL OR p_subject IS NULL OR
   SYS.UTL_RAW.LENGTH(p_issuer)>512 OR SYS.UTL_RAW.LENGTH(p_subject)>256 THEN
   RAISE_APPLICATION_ERROR(-20001,'Workspace access denied.');
  END IF;
  SELECT o.id INTO p_owner FROM owner_identities i JOIN owners o ON o.id=i.owner_id
   WHERE i.issuer=p_issuer AND i.subject=p_subject AND o.is_active=1;
 EXCEPTION WHEN NO_DATA_FOUND THEN p_owner:=NULL;
 END resolve_owner;
END identity_lookup;"""

PREFERENCE_REVISION = """CREATE OR REPLACE TRIGGER preference_revision
 BEFORE INSERT OR UPDATE ON workspace_preferences FOR EACH ROW
BEGIN
 IF INSERTING THEN
  :NEW.revision:=1; :NEW.created_at:=SYSTIMESTAMP;
 ELSE
  IF :NEW.owner_id<>:OLD.owner_id OR :OLD.revision>=9007199254740991 THEN
   RAISE_APPLICATION_ERROR(-20003,'Preference update denied.');
  END IF;
  :NEW.revision:=:OLD.revision+1; :NEW.created_at:=:OLD.created_at;
 END IF;
 :NEW.updated_at:=SYSTIMESTAMP;
END;"""

IMMUTABLE_IDENTITIES = """CREATE OR REPLACE TRIGGER identity_immutable
 BEFORE UPDATE OR DELETE ON owner_identities
BEGIN
 RAISE_APPLICATION_ERROR(-20004,'Identity binding is immutable.');
END;"""

OWNER_IDENTITY = """CREATE OR REPLACE TRIGGER owner_identity_immutable
 BEFORE UPDATE ON owners FOR EACH ROW
BEGIN
 IF :NEW.id<>:OLD.id OR :NEW.created_at<>:OLD.created_at THEN
  RAISE_APPLICATION_ERROR(-20004,'Owner identity is immutable.');
 END IF;
END;"""


def policy_sql(table: str, function: str) -> str:
    if (table, function) not in {
        ("OWNERS", "OWNER_FILTER"),
        ("WORKSPACE_PREFERENCES", "PREFERENCE_FILTER"),
    }:
        raise ValueError("Unknown baseline policy.")
    return f"""BEGIN SYS.DBMS_RLS.ADD_POLICY(object_schema=>'TRADING_MIGRATOR',
 object_name=>'{table}',policy_name=>'OWNER_SCOPE',function_schema=>'TRADING_MIGRATOR',
 policy_function=>'{function}',statement_types=>'SELECT,INSERT,UPDATE,DELETE',
 update_check=>TRUE,enable=>TRUE,policy_type=>SYS.DBMS_RLS.CONTEXT_SENSITIVE); END;"""


OBJECT_STEPS = (
    Step("owners", OWNERS, "TABLE", "OWNERS", OWNER_TABLE),
    Step("identities", IDENTITIES, "TABLE", "OWNER_IDENTITIES", IDENTITY_TABLE),
    Step("preferences", PREFERENCES, "TABLE", "WORKSPACE_PREFERENCES", PREFERENCE_TABLE),
    Step("context_spec", CONTEXT_SPEC, "PACKAGE", "OWNER_CONTEXT"),
    Step("context_body", CONTEXT_BODY, "PACKAGE BODY", "OWNER_CONTEXT"),
    Step("owner_filter", OWNER_FILTER, "FUNCTION", "OWNER_FILTER"),
    Step("preference_filter", PREFERENCE_FILTER, "FUNCTION", "PREFERENCE_FILTER"),
    Step("lookup_spec", IDENTITY_SPEC, "PACKAGE", "IDENTITY_LOOKUP"),
    Step("lookup_body", IDENTITY_BODY, "PACKAGE BODY", "IDENTITY_LOOKUP"),
    Step("preference_revision", PREFERENCE_REVISION, "TRIGGER", "PREFERENCE_REVISION"),
    Step("identity_immutable", IMMUTABLE_IDENTITIES, "TRIGGER", "IDENTITY_IMMUTABLE"),
    Step("owner_immutable", OWNER_IDENTITY, "TRIGGER", "OWNER_IDENTITY_IMMUTABLE"),
    Step("owner_policy", policy_sql("OWNERS", "OWNER_FILTER"), "POLICY", "OWNERS"),
    Step(
        "preference_policy",
        policy_sql("WORKSPACE_PREFERENCES", "PREFERENCE_FILTER"),
        "POLICY",
        "WORKSPACE_PREFERENCES",
    ),
)

GRANTS = (
    Grant("TRADING_RUNTIME", "INSTALLATION", "SELECT"),
    Grant("TRADING_AUTH", "INSTALLATION", "SELECT"),
    Grant("TRADING_RUNTIME", "OWNERS", "SELECT"),
    Grant("TRADING_RUNTIME", "WORKSPACE_PREFERENCES", "SELECT"),
    Grant(
        "TRADING_RUNTIME",
        "WORKSPACE_PREFERENCES",
        "INSERT",
        ("OWNER_ID", "THEME", "DISPLAY_CURRENCY", "AMOUNT_MASKED"),
    ),
    Grant(
        "TRADING_RUNTIME",
        "WORKSPACE_PREFERENCES",
        "UPDATE",
        ("THEME", "DISPLAY_CURRENCY", "AMOUNT_MASKED"),
    ),
    Grant("TRADING_RUNTIME", "OWNER_CONTEXT", "EXECUTE"),
    Grant("TRADING_AUTH", "IDENTITY_LOOKUP", "EXECUTE"),
)

STEPS = OBJECT_STEPS + tuple(
    Step(
        "grant_" + str(index),
        "GRANT "
        + grant.privilege
        + ("(" + ",".join(grant.columns) + ")" if grant.columns else "")
        + " ON "
        + grant.object
        + " TO "
        + grant.grantee,
        "GRANT",
        grant.object,
        grant=grant,
    )
    for index, grant in enumerate(GRANTS, 1)
)

BASELINE_CHECKSUM = hashlib.sha256("\n".join(step.checksum for step in STEPS).encode()).hexdigest()
