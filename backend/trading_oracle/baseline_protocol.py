"""Bounded, credential-free messages and source binding for the local baseline verifier."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

STAGES = (
    "setup",
    "bootstrap",
    "migration",
    "seed",
    "unlock",
    "ownership",
    "identity",
    "preferences",
    "custody",
    "concurrency",
    "schema",
    "clients_closed",
)
SOURCE_FILES = tuple(
    "backend/trading_oracle/" + name + ".py"
    for name in (
        "__init__",
        "local",
        "probe",
        "contracts",
        "schema",
        "bootstrap",
        "metadata",
        "migrate",
        "connections",
        "workspace",
        "identity",
        "baseline",
        "baseline_probe",
        "baseline_protocol",
    )
) + (
    "backend/oracle_tests/__init__.py",
    "backend/oracle_tests/acceptance.py",
    "backend/trading_db/workspace.py",
    "backend/pyproject.toml",
    "backend/uv.lock",
)


def digest(root: Path) -> str:
    entries = []
    for name in SOURCE_FILES:
        path = root / name
        if path.resolve() != path or path.stat().st_size > 2_000_000:
            raise ValueError("Oracle baseline source is unavailable.")
        entries.append(name + ":" + hashlib.sha256(path.read_bytes()).hexdigest())
    return hashlib.sha256("\n".join(entries).encode("ascii")).hexdigest()


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Invalid Oracle baseline result.")
        result[key] = value
    return result


def parse(raw: str, expected_source: str) -> dict[str, Any]:
    if len(raw) > 2048:
        raise ValueError("Invalid Oracle baseline result.")
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != {
        "version",
        "status",
        "stage",
        "completed",
        "error_code",
        "source_sha256",
    }:
        raise ValueError("Invalid Oracle baseline result.")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Invalid Oracle baseline result.")
    if type(expected_source) is not str or not re.fullmatch("[0-9a-f]{64}", expected_source):
        raise ValueError("Invalid Oracle baseline source.")
    if value["source_sha256"] != expected_source:
        raise ValueError("Oracle baseline source changed.")
    completed = value["completed"]
    if type(completed) is not list or completed != list(STAGES[: len(completed)]):
        raise ValueError("Invalid Oracle baseline result.")
    code = value["error_code"]
    if code is not None and (type(code) is not int or not 0 <= code <= 65535):
        raise ValueError("Invalid Oracle baseline result.")
    if value["status"] == "passed":
        if completed != list(STAGES) or value["stage"] != STAGES[-1] or code is not None:
            raise ValueError("Invalid Oracle baseline result.")
    elif value["status"] == "failed":
        if len(completed) >= len(STAGES) or value["stage"] != STAGES[len(completed)]:
            raise ValueError("Invalid Oracle baseline result.")
    else:
        raise ValueError("Invalid Oracle baseline result.")
    return value
