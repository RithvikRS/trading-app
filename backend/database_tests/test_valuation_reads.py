"""Selected source evidence remains distinct from historical intent and stale records."""

from uuid import uuid4

import pytest

from database_tests.test_events import seed
from database_tests.test_instruments import security
from database_tests.test_lots_corrections import cancellation, reviewed
from database_tests.test_preferences import environment as environment
from database_tests.test_preferences import login, sql
from database_tests.test_snapshots import snapshot_candidate
from tests.auth_support import ISSUER, SUBJECT
from tests.test_markets import definition
from trading_db.account_keys import ReferenceKeys
from trading_db.accounts import AccountDatabase, AccountTransaction
from trading_db.enrollment import provision_owner
from trading_db.instruments import InstrumentTransaction, ListingDefinition, SchemeDefinition
from trading_db.markets import MarketTransaction
from trading_db.snapshots import SnapshotTransaction


def get(client, headers, path, **body):
    return client.post(f"/api/v1/finance/{path}", headers=headers, json=body)


def populate(accounts, workspace, owner):
    account, source, position, initial = seed(accounts, owner=owner)
    reference = initial[0].definition.instrument_identifier_id
    rows = reviewed(
        accounts,
        source.id,
        snapshot_candidate(reference, as_of_instant="2026-10-24T00:30:00.120+05:30"),
        snapshot_candidate(amount="0.00", currency="INR", occurrence=2),
        owner=owner,
    )
    with workspace.transaction(owner) as unit:
        snapshots = SnapshotTransaction(unit)
        holding = snapshots.record(rows[0].id, position_id=position.id, expected_review_revision=1)
        cash = snapshots.record(rows[1].id, expected_review_revision=1)
        choices = [
            snapshots.select(item.id, expected_snapshot_revision=1, expected_revision=0)
            for item in (holding, cash)
        ]
        listing = InstrumentTransaction(unit).listings(position.instrument_id)[0]
        markets = MarketTransaction(unit)
        fx = markets.record(definition())
        reverse = markets.record(
            definition(
                occurrence=2, base_currency="INR", quote_currency="USD", source="0.012030299022"
            )
        )
        price = markets.record(
            definition(
                kind="quote",
                instrument_id=position.instrument_id,
                listing_id=listing.id,
                currency="USD",
                base_currency=None,
                quote_currency=None,
                basis="close",
                adjustment="unadjusted",
                occurrence=3,
                observed_at="2026-10-24T00:30:00.120+05:30",
                source="325.123456789012",
            )
        )
        market_choices = [
            markets.select(item.id, expected_revision=0) for item in (fx, reverse, price)
        ]
    return dict(
        account=account,
        source=source,
        position=position,
        reference=reference,
        holding=holding,
        cash=cash,
        choices=choices,
        listing=listing,
        fx=fx,
        reverse=reverse,
        price=price,
        market_choices=market_choices,
    )


@pytest.fixture
def evidence(environment, database):
    _, _, workspace, _, admin = environment
    owner = sql(
        admin,
        "SELECT owner_id FROM app.owner_identities WHERE subject=:subject",
        subject=str(SUBJECT),
    )[0][0]
    url, project = database
    accounts = AccountDatabase(url("runtime"), project, ReferenceKeys({1: b"h" * 32}, 1))
    try:
        yield owner, populate(accounts, workspace, owner), accounts
    finally:
        accounts.close()


def test_snapshot_precision_scopes_zero_and_selected_evidence(environment, evidence):
    client, _, _, _, _ = environment
    _, data, _ = evidence
    headers = login(client)
    response = get(client, headers, "snapshots/query", account_id=str(data["account"].id))
    assert response.status_code == 200
    records = {item["id"]: item for item in response.json()["items"]}
    holding, cash = records[str(data["holding"].id)], records[str(data["cash"].id)]
    assert (
        holding["as_of_date"] == "2026-10-24"
        and holding["as_of_instant"] == "2026-10-24T00:30:00.120+05:30"
    )
    assert (
        holding["snapshot_scope"] == "selected_position"
        and holding["coverage"] == "partial_activity"
    )
    values = {item["role"]: item for item in holding["components"]}
    assert values["quantity"]["source"] == "0.123456789012"
    assert (
        values["unit_price"]["source"] is None
        and values["unit_price"]["missing_reason"] == "not_supplied"
    )
    assert (
        cash["as_of_instant"] is None
        and cash["currency"] == "INR"
        and cash["components"][0]["source"] == "0.00"
    )
    assert holding["reconciliation_boundary"] is None
    for choice in data["choices"]:
        resolved = get(client, headers, "snapshots/selections/resolve", id=str(choice.id))
        assert resolved.status_code == 200 and resolved.json()["state"] == "selected"
        assert resolved.json()["snapshot"] == records[str(choice.snapshot_id)]
    assert all(
        term not in response.text
        for term in ("digest", "owner_id", "fingerprint", "encrypted_reference")
    )


def test_snapshot_correction_stales_choice_then_clear_and_history_remain(environment, evidence):
    client, _, workspace, _, _ = environment
    owner, data, accounts = evidence
    headers = login(client)
    changed = reviewed(
        accounts,
        data["source"].id,
        snapshot_candidate(data["reference"], amount="1.000000000001"),
        owner=owner,
    )[0]
    with workspace.transaction(owner) as unit:
        snapshots = SnapshotTransaction(unit)
        new = snapshots.correct(
            data["holding"].id,
            changed.id,
            expected_revision=1,
            expected_review_revision=1,
            reason="source_correction",
        )
    choice_id = str(data["choices"][0].id)
    stale = get(client, headers, "snapshots/selections/resolve", id=choice_id).json()
    assert (
        stale["state"] == "stale"
        and stale["snapshot"] is None
        and stale["selection"]["snapshot_revision"] == 1
    )
    with workspace.transaction(owner) as unit:
        snapshots = SnapshotTransaction(unit)
        snapshots.select(
            new.id, expected_snapshot_revision=2, expected_revision=1, reason="correction"
        )
        snapshots.clear(data["choices"][0].id, expected_revision=2)
    cleared = get(client, headers, "snapshots/selections/resolve", id=choice_id).json()
    assert cleared["state"] == "unselected" and cleared["snapshot"] is None
    history = get(client, headers, "snapshots/selections/history", id=choice_id).json()["items"]
    assert [item["revision"] for item in history] == [3, 2, 1]
    assert [item["is_current"] for item in history] == [True, False, False]
    assert history[1]["snapshot_revision"] == 2 and history[2]["snapshot_revision"] == 1
    versions = get(client, headers, "snapshots/history", id=str(new.id)).json()["items"]
    assert [item["revision"] for item in versions] == [2, 1]
    assert versions[0]["as_of_instant"] is None and versions[1]["as_of_instant"] is not None


def test_snapshot_mapping_and_archive_prevent_releasing_selected_values(environment, evidence):
    client, _, workspace, _, _ = environment
    owner, data, accounts = evidence
    headers = login(client)
    with accounts.transaction(owner) as unit:
        unit.map(data["source"].id, None, expected_revision=1)
    for choice in data["choices"]:
        stale = get(client, headers, "snapshots/selections/resolve", id=str(choice.id)).json()
        assert stale["state"] == "stale" and stale["snapshot"] is None
    with workspace.transaction(owner) as unit:
        AccountTransaction(unit, None).archive(data["account"].id, expected_revision=1)
    for choice in data["choices"]:
        archived = get(client, headers, "snapshots/selections/resolve", id=str(choice.id)).json()
        assert archived["state"] == "archived" and archived["snapshot"] is None
    assert (
        get(client, headers, "snapshots/query", account_id=str(data["account"].id)).status_code
        == 200
    )


def test_snapshot_conflicts_remain_unavailable_then_cancellation_history_is_visible(
    environment, evidence
):
    client, _, workspace, _, _ = environment
    owner, data, accounts = evidence
    headers = login(client)
    with accounts.transaction(owner) as unit:
        source = unit.source("indmoney_us", "FAKE-SNAPSHOT-OTHER")
        unit.map(source.id, data["account"].id, expected_revision=0)
    row = reviewed(
        accounts,
        source.id,
        snapshot_candidate(
            data["reference"], amount="11", as_of_instant="2026-10-24T00:30:00.120+05:30"
        ),
        owner=owner,
    )[0]
    with workspace.transaction(owner) as unit:
        conflict = SnapshotTransaction(unit).record(
            row.id, expected_review_revision=1, position_id=data["position"].id
        )
    response = get(
        client, headers, "snapshots/selections/resolve", id=str(data["choices"][0].id)
    ).json()
    assert response["state"] == "conflicting" and response["snapshot"] is None
    cancelled = reviewed(accounts, source.id, cancellation(), owner=owner)[0]
    with workspace.transaction(owner) as unit:
        SnapshotTransaction(unit).correct(
            conflict.id,
            cancelled.id,
            expected_revision=1,
            expected_review_revision=1,
            reason="cancellation",
        )
    assert (
        get(client, headers, "snapshots/selections/resolve", id=str(data["choices"][0].id)).json()[
            "state"
        ]
        == "selected"
    )
    history = get(client, headers, "snapshots/history", id=str(conflict.id)).json()["items"]
    assert history[0]["status"] == "cancelled" and history[0]["components"] == []
    assert history[1]["status"] == "active"


def test_quotes_and_directed_fx_preserve_precision_and_separate_native_targets(
    environment, evidence
):
    client, _, _, _, _ = environment
    _, data, _ = evidence
    headers = login(client)
    quotes = get(
        client,
        headers,
        "markets/observations/query",
        kind="quote",
        instrument_id=str(data["position"].instrument_id),
    ).json()["items"]
    assert (
        len(quotes) == 1
        and quotes[0]["source"] == "325.123456789012"
        and quotes[0]["currency"] == "USD"
    )
    assert (
        quotes[0]["observed_at"] == "2026-10-24T00:30:00.120+05:30"
        and quotes[0]["adjustment"] == "unadjusted"
    )
    listing = get(
        client, headers, "listings/query", instrument_id=str(data["position"].instrument_id)
    ).json()["items"][0]
    assert (
        listing["id"] == quotes[0]["listing_id"]
        and listing["venue"] == "XNYS"
        and listing["series"] == ""
    )
    fx = get(client, headers, "markets/observations/query", kind="fx").json()["items"]
    assert {(item["base_currency"], item["quote_currency"], item["source"]) for item in fx} == {
        ("USD", "INR", "83.123456789012"),
        ("INR", "USD", "0.012030299022"),
    }
    assert all(item["observed_at"] is None for item in fx)
    for choice in data["market_choices"]:
        result = get(client, headers, "markets/selections/resolve", id=str(choice.id))
        assert result.status_code == 200 and result.json()["state"] == "selected"
        assert result.json()["observation"]["id"] == str(choice.observation_id)
        assert "digest" not in result.text and "owner_id" not in result.text


def test_market_correction_stales_selection_and_unusable_evidence_is_inspectable(
    environment, evidence
):
    client, _, workspace, _, _ = environment
    owner, data, _ = evidence
    headers = login(client)
    with workspace.transaction(owner) as unit:
        markets = MarketTransaction(unit)
        changed = markets.record(
            data["fx"].definition.model_copy(
                update={
                    "previous_id": data["fx"].id,
                    "digest": "b" * 64,
                    "source": "84.000000000001",
                }
            )
        )
        unusable = [
            markets.record(definition(occurrence=index + 10, source=source, missing_reason=reason))
            for index, (source, reason) in enumerate(
                ((None, "not_supplied"), ("0.00", None), ("-1", None))
            )
        ]
        adjusted = markets.record(
            data["price"].definition.model_copy(
                update={"occurrence": 20, "adjustment": "split_adjusted"}
            )
        )
    choice = data["market_choices"][0]
    response = get(client, headers, "markets/selections/resolve", id=str(choice.id)).json()
    assert response["state"] == "stale" and response["observation"] is None
    old = get(client, headers, "markets/observations/inspect", id=str(data["fx"].id)).json()
    new = get(client, headers, "markets/observations/inspect", id=str(changed.id)).json()
    assert not old["is_current"] and old["usable"] and new["previous_id"] == old["id"]
    for item in [*unusable, adjusted]:
        record = get(client, headers, "markets/observations/inspect", id=str(item.id)).json()
        assert not record["usable"] and record["source"] == item.definition.source
    with workspace.transaction(owner) as unit:
        markets = MarketTransaction(unit)
        markets.select(changed.id, expected_revision=1, reason="correction")
        markets.clear(choice.id, expected_revision=2)
    assert (
        get(client, headers, "markets/selections/resolve", id=str(choice.id)).json()["state"]
        == "unselected"
    )
    history = get(client, headers, "markets/selections/history", id=str(choice.id)).json()["items"]
    assert [item["revision"] for item in history] == [3, 2, 1]
    assert history[1]["observation_id"] == str(changed.id) and history[-1]["observation_id"] == str(
        data["fx"].id
    )


def queries(data):
    return [
        ("snapshots/query", dict(account_id=str(data["account"].id))),
        ("snapshots/history", dict(id=str(data["holding"].id))),
        ("snapshots/selections/query", dict(account_id=str(data["account"].id))),
        ("snapshots/selections/history", dict(id=str(data["choices"][0].id))),
        ("snapshots/selections/resolve", dict(id=str(data["choices"][0].id))),
        ("listings/query", dict(instrument_id=str(data["position"].instrument_id))),
        (
            "markets/observations/query",
            dict(kind="quote", instrument_id=str(data["position"].instrument_id)),
        ),
        ("markets/observations/inspect", dict(id=str(data["price"].id))),
        (
            "markets/selections/query",
            dict(kind="quote", instrument_id=str(data["position"].instrument_id)),
        ),
        ("markets/selections/history", dict(id=str(data["market_choices"][2].id))),
        ("markets/selections/resolve", dict(id=str(data["market_choices"][2].id))),
    ]


def test_all_parent_scopes_hide_foreign_and_missing_ids_and_require_session(
    environment, evidence, database
):
    client, _, workspace, _, admin = environment
    owner, data, accounts = evidence
    url, project = database
    provision_owner(url("bootstrap"), project, ISSUER, uuid4())
    other = sql(admin, "SELECT id FROM app.owners WHERE id<>:owner", owner=owner)[0][0]
    foreign = populate(accounts, workspace, other)
    headers = login(client)
    for path, body in queries(foreign):
        for target in (
            body,
            {key: value if key == "kind" else str(uuid4()) for key, value in body.items()},
        ):
            response = get(client, headers, path, **target)
            assert response.status_code == 404 and set(response.json()) == {"error", "request_id"}
    for path, body in queries(data):
        assert get(client, {}, path, **body).status_code == 403
        assert get(client, headers, path + "?limit=1", **body).status_code == 403
        assert get(client, headers, path, **body, owner_id=str(other)).status_code == 422
    client.cookies.delete("trading_dev_session")
    for path, body in queries(data):
        assert get(client, headers, path, **body).status_code == 401


def test_pages_and_history_cursors_preserve_all_evidence(environment, evidence):
    client, _, _, _, _ = environment
    _, data, _ = evidence
    headers = login(client)
    for path, body in [
        *queries(data),
        ("markets/observations/query", dict(kind="fx")),
        ("markets/selections/query", dict(kind="fx")),
    ]:
        if path.endswith(("resolve", "inspect")):
            continue
        records = get(client, headers, path, **body).json()["items"]
        field = "before" if path.endswith("history") else "after"
        seen, cursor = [], None
        for _ in range(len(records) + 1):
            response = get(client, headers, path, **body, **{field: cursor}, limit=1)
            assert response.status_code == 200
            result = response.json()
            seen.extend(result["items"])
            cursor = result["next_" + field]
            if cursor is None:
                break
        assert seen == records


def test_nav_variants_and_quote_listings_remain_distinct_targets(environment, evidence):
    client, _, workspace, _, _ = environment
    owner, data, _ = evidence
    with workspace.transaction(owner) as unit:
        identities = InstrumentTransaction(unit)
        scheme = identities.scheme(SchemeDefinition(name="Synthetic shared fund scheme"))
        funds = [
            identities.create(
                security(
                    index + 1,
                    "mutual_fund",
                    fund_scheme_id=scheme.id,
                    fund_plan=plan,
                    fund_option="growth",
                    fund_currency="INR",
                )
            )
            for index, plan in enumerate(("direct", "regular"))
        ]
        markets = MarketTransaction(unit)
        navs = [
            markets.record(
                definition(
                    kind="nav",
                    instrument_id=fund.id,
                    currency="INR",
                    base_currency=None,
                    quote_currency=None,
                    basis="nav",
                    namespace="amfi_nav_report",
                    occurrence=index + 21,
                    source="108.123456789012",
                )
            )
            for index, fund in enumerate(funds)
        ]
        listing = identities.listing(
            data["position"].instrument_id,
            ListingDefinition(venue="XNAS", symbol="FAKE", quote_currency="USD"),
        )
        quote = markets.record(
            data["price"].definition.model_copy(
                update={"listing_id": listing.id, "occurrence": 30, "source": "326.123456789012"}
            )
        )
        for item in [*navs, quote]:
            markets.select(item.id, expected_revision=0)
    headers = login(client)
    for fund, nav in zip(funds, navs, strict=True):
        page = get(
            client, headers, "markets/observations/query", kind="nav", instrument_id=str(fund.id)
        )
        assert page.status_code == 200 and len(page.json()["items"]) == 1
        record = page.json()["items"][0]
        assert record["id"] == str(nav.id) and record["currency"] == "INR"
        assert record["listing_id"] is None and record["adjustment"] is None
    prices = get(
        client,
        headers,
        "markets/observations/query",
        kind="quote",
        instrument_id=str(data["position"].instrument_id),
    ).json()["items"]
    assert {(item["listing_id"], item["source"]) for item in prices} == {
        (str(data["listing"].id), "325.123456789012"),
        (str(listing.id), "326.123456789012"),
    }
