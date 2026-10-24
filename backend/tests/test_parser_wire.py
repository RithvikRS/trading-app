"""Fabricated streams exercise bounds and ambiguity before any native parser runs."""

import json
import socket
import threading

import pytest

from trading_parser import wire
from trading_parser.wire import (
    ParserReply,
    ParserRequest,
    ProtocolUnavailable,
    deadline,
    receive_reply,
    receive_request,
    send_reply,
    send_request,
)

ATTEMPT = "a" * 32


def request(**changes):
    return ParserRequest(
        **(
            dict(
                attempt=ATTEMPT,
                operation="parse",
                adapter="cams_detailed_v1",
                password="synthetic-password",
                document=b"fabricated bytes",
            )
            | changes
        )
    )


def metadata(**changes):
    return (
        dict(
            version=1,
            attempt=ATTEMPT,
            operation="parse",
            adapter="cams_detailed_v1",
            password="synthetic-password",
        )
        | changes
    )


class Stream:
    """Finite chunks; exhaustion distinguishes an expected EOF from an unwanted body read."""

    def __init__(self, *chunks):
        self.chunks = list(chunks)
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def recv(self, count):
        assert self.chunks, "Unexpected read past the supplied header or metadata"
        chunk = self.chunks.pop(0)
        if len(chunk) > count:
            self.chunks.insert(0, chunk[count:])
        return chunk[:count]


def framed(meta=None, document=b"fabricated bytes", tail=b""):
    encoded = json.dumps(meta or metadata()).encode()
    return Stream(
        wire.REQUEST_HEADER.pack(b"TPR1", len(encoded), len(document)), encoded, document, tail
    )


def test_fragmented_metadata_password_and_document_roundtrip_without_repr_disclosure():
    original = request(password="synthetic-\u20b9-\U0001f9ed")
    client, worker = socket.socketpair()
    failures = []

    def serve():
        try:
            end = deadline(5)
            incoming = receive_request(worker, end)
            assert incoming == original
            send_reply(worker, ParserReply(incoming.attempt, "unsupported_format"), end)
        except Exception as error:
            failures.append(error)
        finally:
            worker.close()

    task = threading.Thread(target=serve, daemon=True)
    task.start()
    try:
        end = deadline(5)
        send_request(client, original, end)
        reply = receive_reply(client, original, end)
        assert reply.status == "unsupported_format"
    finally:
        client.close()
        task.join(6)
    assert not task.is_alive() and not failures
    assert original.password not in repr(original) and "fabricated" not in repr(original)


def test_probe_has_no_document_adapter_or_password_and_ready_is_probe_only():
    probe = request(operation="probe", adapter=None, password="", document=b"")
    payload = json.dumps(dict(version=1, attempt=ATTEMPT, status="ready")).encode()

    def response():
        return Stream(wire.REPLY_HEADER.pack(b"TPS1", len(payload)), payload, b"")

    assert receive_reply(response(), probe, deadline(2)).status == "ready"
    with pytest.raises(ProtocolUnavailable):
        receive_reply(response(), request(), deadline(2))
    for changes in ({"document": b"x"}, {"adapter": "cams_detailed_v1"}, {"password": "x"}):
        with pytest.raises(ProtocolUnavailable):
            request(operation="probe", **(dict(adapter=None, password="", document=b"") | changes))


@pytest.mark.parametrize(
    "magic,meta_size,doc_size",
    [
        (b"BAD!", 1, 1),
        (b"TPR1", 0, 1),
        (b"TPR1", wire.MAX_METADATA + 1, 1),
        (b"TPR1", 1, wire.MAX_DOCUMENT + 1),
    ],
)
def test_invalid_header_denies_before_any_body_read(magic, meta_size, doc_size):
    stream = Stream(wire.REQUEST_HEADER.pack(magic, meta_size, doc_size))
    with pytest.raises(ProtocolUnavailable):
        receive_request(stream, deadline(2))


@pytest.mark.parametrize(
    "changes",
    [
        {"version": True},
        {"version": "1"},
        {"version": 2},
        {"owner_id": "foreign"},
        {"file_path": "/private"},
        {"attempt": "A" * 32},
        {"attempt": 7},
        {"operation": ["parse"]},
        {"adapter": "../../execute"},
        {"password": None},
        {"password": "x" * 257},
        {"password": "x\x00y"},
        {"password": "\ud800"},
    ],
)
def test_invalid_metadata_denies_before_document_allocation(changes):
    encoded = json.dumps(metadata(**changes)).encode()
    stream = Stream(wire.REQUEST_HEADER.pack(b"TPR1", len(encoded), 1), encoded)
    with pytest.raises(ProtocolUnavailable) as error:
        receive_request(stream, deadline(2))
    assert str(error.value) == "Document processing is unavailable."


@pytest.mark.parametrize(
    "encoded",
    [
        b'{"version":1,"version":1}',
        b'{"version":NaN}',
        b"[]",
        b"null",
        b"\xff",
        b"[" * 1000 + b"]" * 1000,
    ],
)
def test_duplicate_nonfinite_nested_and_invalid_json_never_reaches_document(encoded):
    stream = Stream(wire.REQUEST_HEADER.pack(b"TPR1", len(encoded), 1), encoded)
    with pytest.raises(ProtocolUnavailable):
        receive_request(stream, deadline(2))


def test_partial_body_and_extra_bytes_cannot_become_a_completed_request():
    encoded = json.dumps(metadata()).encode()
    for body, tail in ((b"x", b""), (b"xy", b"extra")):
        stream = Stream(wire.REQUEST_HEADER.pack(b"TPR1", len(encoded), 2), encoded, body, tail)
        with pytest.raises(ProtocolUnavailable):
            receive_request(stream, deadline(2))


def test_fragmented_bytes_keep_one_deadline_instead_of_resetting_it(monkeypatch):
    now = iter((10.0, 10.25, 10.75, 11.01))
    monkeypatch.setattr(wire.time, "monotonic", lambda: next(now))
    end = deadline(1)
    stream = Stream(b"T", b"P", b"R")
    with pytest.raises(ProtocolUnavailable):
        receive_request(stream, end)
    assert stream.timeouts == [0.75, 0.25]
    assert stream.chunks == [b"R"]


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt": "b" * 32},
        {"status": "parsed"},
        {"status": "synthetic-secret"},
        {"rows": []},
        {"version": True},
    ],
)
def test_unexpected_reply_never_claims_supported_parsing_or_crosses_attempts(changes):
    data = json.dumps(
        dict(version=1, attempt=ATTEMPT, status="unsupported_format") | changes
    ).encode()
    stream = Stream(wire.REPLY_HEADER.pack(b"TPS1", len(data)), data, b"")
    with pytest.raises(ProtocolUnavailable):
        receive_reply(stream, request(), deadline(2))


@pytest.mark.parametrize(
    "seconds", [0, -1, 61, 10**1000, -(10**1000), True, "5", float("nan"), float("inf")]
)
def test_invalid_deadlines_cannot_disable_limits(seconds):
    with pytest.raises(ProtocolUnavailable):
        deadline(seconds)


def test_metadata_and_doc_size_agree_before_body_read():
    for meta, length in (
        (metadata(operation="probe", adapter=None, password=""), 1),
        (metadata(), 0),
    ):
        encoded = json.dumps(meta).encode()
        stream = Stream(wire.REQUEST_HEADER.pack(b"TPR1", len(encoded), length), encoded)
        with pytest.raises(ProtocolUnavailable):
            receive_request(stream, deadline(2))


@pytest.mark.parametrize(
    "magic,length", [(b"BAD!", 1), (b"TPS1", 0), (b"TPS1", wire.MAX_REPLY + 1)]
)
def test_worker_reply_size_is_rejected_before_reading_payload(magic, length):
    stream = Stream(wire.REPLY_HEADER.pack(magic, length))
    with pytest.raises(ProtocolUnavailable):
        receive_reply(stream, request(), deadline(2))


@pytest.mark.parametrize("truncate,tail", [(True, b""), (False, b"extra-output")])
def test_worker_reply_requires_complete_and_exclusive_frame(truncate, tail):
    data = json.dumps(dict(version=1, attempt=ATTEMPT, status="unsupported_format")).encode()
    stream = Stream(
        wire.REPLY_HEADER.pack(b"TPS1", len(data)), data[:-1] if truncate else data, tail
    )
    with pytest.raises(ProtocolUnavailable):
        receive_reply(stream, request(), deadline(2))
