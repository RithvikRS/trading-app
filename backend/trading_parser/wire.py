"""One bounded request/reply per local stream; no file paths or process commands."""

import json
import math
import re
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any, Literal

MAX_DOCUMENT = 8 * 1024 * 1024
MAX_METADATA = 2048
MAX_REPLY = 512
REQUEST_HEADER = struct.Struct("!4sHI")
REPLY_HEADER = struct.Struct("!4sI")
type Operation = Literal["probe", "parse"]
type Adapter = Literal["cams_detailed_v1", "kfin_detailed_v1"]
type Status = Literal["ready", "unsupported_format", "invalid_input", "unavailable", "busy"]
_STATUSES = {"ready", "unsupported_format", "invalid_input", "unavailable", "busy"}
_ADAPTERS = {"cams_detailed_v1", "kfin_detailed_v1"}


class ProtocolUnavailable(ValueError):
    def __init__(self) -> None:
        super().__init__("Document processing is unavailable.")


def attempt(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value, re.ASCII) is None:
        raise ProtocolUnavailable()
    return value


def _metadata(
    identifier: str,
    operation: Operation,
    adapter: Adapter | None,
    password: str,
    document_size: int,
) -> None:
    attempt(identifier)
    if (
        type(password) is not str
        or len(password) > 256
        or "\x00" in password
        or type(document_size) is not int
        or not 0 <= document_size <= MAX_DOCUMENT
        or type(operation) is not str
    ):
        raise ProtocolUnavailable()
    try:
        if len(password.encode("utf-8")) > 1024:
            raise ProtocolUnavailable()
    except UnicodeError:
        raise ProtocolUnavailable() from None
    if operation == "probe":
        if adapter is not None or password or document_size:
            raise ProtocolUnavailable()
    elif operation == "parse":
        if type(adapter) is not str or adapter not in _ADAPTERS or document_size == 0:
            raise ProtocolUnavailable()
    else:
        raise ProtocolUnavailable()


@dataclass(frozen=True, slots=True, repr=False)
class ParserRequest:
    attempt: str
    operation: Operation
    adapter: Adapter | None
    password: str
    document: bytes

    def __post_init__(self) -> None:
        if type(self.document) is not bytes:
            raise ProtocolUnavailable()
        _metadata(self.attempt, self.operation, self.adapter, self.password, len(self.document))


@dataclass(frozen=True, slots=True, repr=False)
class ParserReply:
    attempt: str
    status: Status

    def __post_init__(self) -> None:
        attempt(self.attempt)
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ProtocolUnavailable()


def deadline(seconds: float) -> float:
    if type(seconds) not in {int, float} or not 0 < seconds <= 60 or not math.isfinite(seconds):
        raise ProtocolUnavailable()
    return time.monotonic() + seconds


def _timeout(stream: socket.socket, end: float) -> None:
    remaining = end - time.monotonic()
    if not math.isfinite(remaining) or remaining <= 0:
        raise ProtocolUnavailable()
    stream.settimeout(remaining)


def _receive(stream: socket.socket, count: int, end: float) -> bytes:
    result = bytearray()
    try:
        while len(result) < count:
            _timeout(stream, end)
            chunk = stream.recv(min(65536, count - len(result)))
            if not chunk:
                raise ProtocolUnavailable()
            result.extend(chunk)
    except OSError:
        raise ProtocolUnavailable() from None
    return bytes(result)


def _finished(stream: socket.socket, end: float) -> None:
    try:
        _timeout(stream, end)
        if stream.recv(1):
            raise ProtocolUnavailable()
    except OSError:
        raise ProtocolUnavailable() from None


def _send(stream: socket.socket, parts: tuple[bytes, ...], end: float) -> None:
    try:
        for part in parts:
            _timeout(stream, end)
            stream.sendall(part)
        stream.shutdown(socket.SHUT_WR)
    except OSError:
        raise ProtocolUnavailable() from None


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolUnavailable()
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ProtocolUnavailable()


def _object(data: bytes, fields: set[str]) -> dict[str, Any]:
    try:
        value = json.loads(
            data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_invalid_constant
        )
    except UnicodeError, ValueError, RecursionError:
        raise ProtocolUnavailable() from None
    if (
        type(value) is not dict
        or set(value) != fields
        or type(value.get("version")) is not int
        or value["version"] != 1
    ):
        raise ProtocolUnavailable()
    return value


def send_request(stream: socket.socket, request: ParserRequest, end: float) -> None:
    request.__post_init__()
    metadata = json.dumps(
        dict(
            version=1,
            attempt=request.attempt,
            operation=request.operation,
            adapter=request.adapter,
            password=request.password,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(metadata) > MAX_METADATA:
        raise ProtocolUnavailable()
    _send(
        stream,
        (
            REQUEST_HEADER.pack(b"TPR1", len(metadata), len(request.document)),
            metadata,
            request.document,
        ),
        end,
    )


def receive_request(stream: socket.socket, end: float) -> ParserRequest:
    magic, meta_size, doc_size = REQUEST_HEADER.unpack(_receive(stream, REQUEST_HEADER.size, end))
    if magic != b"TPR1" or not 1 <= meta_size <= MAX_METADATA or doc_size > MAX_DOCUMENT:
        raise ProtocolUnavailable()
    meta = _object(
        _receive(stream, meta_size, end), {"version", "attempt", "operation", "adapter", "password"}
    )
    operation = meta["operation"]
    # Reject invalid metadata and lengths before allocating the document body.
    _metadata(meta["attempt"], operation, meta["adapter"], meta["password"], doc_size)
    body = _receive(stream, doc_size, end)
    _finished(stream, end)
    return ParserRequest(meta["attempt"], operation, meta["adapter"], meta["password"], body)


def send_reply(stream: socket.socket, reply: ParserReply, end: float) -> None:
    reply.__post_init__()
    data = json.dumps(
        dict(version=1, attempt=reply.attempt, status=reply.status), separators=(",", ":")
    ).encode("utf-8")
    if len(data) > MAX_REPLY:
        raise ProtocolUnavailable()
    _send(stream, (REPLY_HEADER.pack(b"TPS1", len(data)), data), end)


def receive_reply(stream: socket.socket, request: ParserRequest, end: float) -> ParserReply:
    magic, length = REPLY_HEADER.unpack(_receive(stream, REPLY_HEADER.size, end))
    if magic != b"TPS1" or not 1 <= length <= MAX_REPLY:
        raise ProtocolUnavailable()
    result = _object(_receive(stream, length, end), {"version", "attempt", "status"})
    _finished(stream, end)
    reply = ParserReply(result["attempt"], result["status"])
    if reply.attempt != request.attempt or (
        reply.status == "ready" and request.operation != "probe"
    ):
        raise ProtocolUnavailable()
    return reply
