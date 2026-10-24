"""Version-four evidence survives migration and restored metadata cannot exceed its contract."""

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database_tests.test_accounts import accounts as accounts
from database_tests.test_accounts import seed
from database_tests.test_imports import batch, observation
from database_tests.test_ownership import OWNER_A
from tests.test_statement_contracts import checkpoint
from trading_db import migrate
from trading_db.imports import ImportTransaction, canonical
from trading_db.recovery import HEAD


def insert_batch(connection, observation_id, *, version, basis=None, digest=None):
    batch_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,normalizer,"
            "normalizer_version,normalized_digest,row_count,contract_version,cash_date_basis) "
            "VALUES (:owner,:id,:observation,1,'synthetic','1',:digest,1,:version,:basis)"
        ),
        dict(
            owner=OWNER_A,
            id=batch_id,
            observation=observation_id,
            version=version,
            basis=basis,
            digest=digest or "a" * 64,
        ),
    )
    return batch_id


@pytest.mark.parametrize("version", (1, 2, 3, 4))
@pytest.mark.parametrize("metadata", ("basis", "boundary"))
def test_legacy_contract_cannot_gain_statement_metadata_even_on_restore(
    accounts, version, metadata
):
    store, admin = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        observed = ImportTransaction(unit._unit).observation(source.id, observation())
    with pytest.raises(DBAPIError), admin.begin() as connection:
        batch_id = insert_batch(
            connection,
            observed.id,
            version=version,
            basis="booking" if metadata == "basis" else None,
        )
        connection.execute(
            text(
                "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,as_of_date,"
                "snapshot_scope,reconciliation_boundary,value_count) VALUES "
                "(:owner,:id,:batch,1,'cash_snapshot','2026-10-24','native_cash','after_period',0)"
            ),
            dict(owner=OWNER_A, id=uuid4(), batch=batch_id),
        )


@pytest.mark.parametrize(
    "coverage,basis", (("unknown", "booking"), ("snapshot", "value"), ("partial_activity", "trade"))
)
def test_sql_rejects_unproved_or_invalid_cash_date_basis(accounts, coverage, basis):
    store, admin = accounts
    _, source = seed(store)
    with store.transaction(OWNER_A) as unit:
        observed = ImportTransaction(unit._unit).observation(
            source.id, observation().model_copy(update={"coverage": coverage})
        )
    with pytest.raises(DBAPIError), admin.begin() as connection:
        insert_batch(connection, observed.id, version=5, basis=basis)


def test_legacy_content_and_metadata_survive_interrupted_upgrade_and_safe_downgrade(
    accounts, database, monkeypatch
):
    store, admin = accounts
    url, project = database
    migrate.apply(url(), project, direction="downgrade", target="0013_event_evidence")
    _, source = seed(store)
    observation_id, batch_id, row_id = uuid4(), uuid4(), uuid4()
    legacy = batch(checkpoint(reconciliation_boundary=None))
    digest = hashlib.sha256(canonical(legacy, 4).encode()).hexdigest()
    assert digest == "d3d80ad53031a16d6869f796275f97d4e5e7a4ceac69585ecb7ee5a52443fab5"
    with store.transaction(OWNER_A) as unit:
        unit._execute(
            "INSERT INTO app.source_observations (owner_id,id,source_id,digest,digest_algorithm,"
            "period_start,period_end,coverage) VALUES (:owner,:id,:source,:digest,'sha256_v1',"
            "'2026-10-24','2026-10-24','partial_activity')",
            id=observation_id,
            source=source.id,
            digest="a" * 64,
        )
        unit._execute(
            "INSERT INTO app.import_batches (owner_id,id,observation_id,revision,normalizer,"
            "normalizer_version,normalized_digest,row_count,contract_version) VALUES "
            "(:owner,:id,:observation,1,'synthetic','1',:digest,1,4)",
            id=batch_id,
            observation=observation_id,
            digest=digest,
        )
        unit._execute(
            "INSERT INTO app.staged_rows (owner_id,id,batch_id,occurrence,kind,as_of_date,"
            "snapshot_scope,value_count) VALUES "
            "(:owner,:id,:batch,1,'cash_snapshot','2026-10-24','native_cash',1)",
            id=row_id,
            batch=batch_id,
        )
        unit._execute(
            "INSERT INTO app.staged_values (owner_id,row_id,role,source,amount,currency) "
            "VALUES (:owner,:row,'net_cash','100.00',100.00,'INR')",
            row=row_id,
        )
    from alembic.operations import Operations

    execute = Operations.execute

    def fail(self, sql, *args, **kwargs):
        result = execute(self, sql, *args, **kwargs)
        if "CREATE FUNCTION app.check_statement_boundary" in str(sql):
            raise RuntimeError("Synthetic migration interruption.")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "execute", fail)
        with pytest.raises(RuntimeError):
            migrate.apply(url(), project)
    assert migrate.revision(url(), project) == "0013_event_evidence"
    with admin.connect() as connection:
        assert not connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='app' "
                "AND column_name IN ('cash_date_basis','reconciliation_boundary'))"
            )
        ).scalar_one()
    migrate.apply(url(), project)
    migrate.apply(url(), project)
    migrate.apply(url(), project, direction="downgrade", target="0013_event_evidence")
    migrate.apply(url(), project)
    with store.transaction(OWNER_A) as unit:
        imports = ImportTransaction(unit._unit)
        assert imports.get_batch(batch_id).definition == legacy
        assert imports.stage(observation_id, legacy, expected_revision=1).id == batch_id
        assert imports.get_row(row_id).definition.reconciliation_boundary is None
        imports.stage(
            observation_id,
            legacy.model_copy(update={"normalizer_version": "2", "cash_date_basis": "booking"}),
            expected_revision=1,
        )
    with pytest.raises(DBAPIError, match="cannot be downgraded"):
        migrate.apply(url(), project, direction="downgrade", target="0013_event_evidence")
    assert migrate.revision(url(), project) == HEAD
    with admin.connect() as connection:
        assert connection.execute(
            text("SELECT normalized_digest,contract_version FROM app.import_batches WHERE id=:id"),
            dict(id=batch_id),
        ).one() == (digest, 4)
