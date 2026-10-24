"""Preview credentials bind the exact request to an owner and original workspace."""

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tests.test_browser_boundary import ORIGIN
from tests.test_browser_boundary import boundary as boundary
from tests.test_completion_contracts import request
from trading_api.snapshot_review import PreviewTokens
from trading_api.snapshot_review_contracts import PreviewCommand
from trading_db.completion_baseline import CompletionUnavailable


def command(**changes):
    return (
        dict(
            idempotency_key=str(uuid4()),
            batch_id=str(uuid4()),
            batch_revision=1,
            rows=[dict(row_id=str(uuid4()), review_revision=1, operation="record")],
        )
        | changes
    )


def test_preview_is_private_bound_tamper_evident_and_invalid_after_restart(monkeypatch):
    tokens, owner, context, value = PreviewTokens(), uuid4(), "a" * 64, request()
    sealed = tokens.seal(owner, context, value)
    assert tokens.open(owner, context, sealed) == value
    assert value.baseline not in sealed and str(value.batch_id) not in sealed
    for other, identity, workspace, token in [
        (tokens, uuid4(), context, sealed),
        (tokens, owner, "b" * 64, sealed),
        (tokens, owner, context, sealed[:-10]),
        (PreviewTokens(), owner, context, sealed),
    ]:
        with pytest.raises(CompletionUnavailable):
            other.open(identity, workspace, token)
    timestamp = tokens._cipher.extract_timestamp(sealed.encode())
    monkeypatch.setattr("cryptography.fernet.time.time", lambda: timestamp + 301)
    with pytest.raises(CompletionUnavailable):
        tokens.open(owner, context, sealed)


@pytest.mark.parametrize(
    "changes",
    [
        {"owner_id": str(uuid4())},
        {"baseline": "a" * 64},
        {"batch_revision": True},
        {"batch_id": str(uuid4()).upper()},
        {"rows": []},
        {
            "rows": [
                dict(
                    row_id=str(uuid4()),
                    review_revision=1,
                    operation="record",
                    target_id=str(uuid4()),
                )
            ]
        },
        {"rows": [dict(row_id=str(uuid4()), review_revision=1, operation="exclude", select=True)]},
        {
            "rows": [
                dict(
                    row_id=str(uuid4()),
                    review_revision=1,
                    operation="record",
                    provider_reference="private",
                )
            ]
        },
    ],
)
def test_preview_commands_reject_ambiguous_authority_and_effects(changes):
    with pytest.raises(ValidationError):
        PreviewCommand.model_validate(command(**changes))


def test_json_manifest_and_full_bounded_batch_round_trip():
    body = command(
        rows=[
            dict(
                row_id=str(uuid4()),
                review_revision=1,
                operation="record",
                position_id=str(uuid4()),
                select=True,
            )
            for _ in range(100)
        ]
    )
    value = PreviewCommand.model_validate_json(json.dumps(body))
    complete = value.completion("b" * 64)
    assert len(complete.rows) == len(complete.selections) == 100
    token = PreviewTokens().seal(uuid4(), "a" * 64, complete)
    assert len(json.dumps(body).encode()) < 65536 and len(token) < 100000


def test_larger_manifest_limits_are_exact_path_only_and_keep_csrf_json_rules(boundary):
    client, called = boundary
    headers = {
        "Origin": ORIGIN,
        "X-CSRFToken": client.cookies["trading_dev_csrf"],
        "Content-Type": "application/json",
    }
    for name, limit in [
        ("preview", 65536),
        ("complete", 131072),
        ("decide", 4096),
        ("unknown", 4096),
    ]:
        path = "/api/v1/finance/snapshot-review/" + name
        assert (
            client.post(path, content=b"{}" + b" " * (limit - 2), headers=headers).status_code
            == 200
        )
        called.clear()
        for body, expected in [
            (b" " * (limit + 1), 413),
            (b'{"id":1,"id":2}', 400),
            (b'{"n":NaN}', 400),
        ]:
            assert client.post(path, content=body, headers=headers).status_code == expected
            assert not called
        assert (
            client.post(
                path, json={}, headers={**headers, "Origin": "https://untrusted.invalid"}
            ).status_code
            == 403
        )
        assert not called
