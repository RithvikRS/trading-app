"""Checksum-verified release tools shared by Windows and Linux checks."""

import hashlib
import io
import json
import platform
import re
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORIES = {"gitleaks": "gitleaks/gitleaks", "actionlint": "rhysd/actionlint"}
MAX_BYTES = 32 * 1024 * 1024


class CheckFailure(RuntimeError):
    """A failed or incomplete verification; never a passing result."""


def verify_hash(payload: bytes, expected: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise CheckFailure("Invalid tool checksum pin.")
    if hashlib.sha256(payload).hexdigest() != expected:
        raise CheckFailure("Tool checksum mismatch; do not execute the file.")


def extract_binary(payload: bytes, asset: str, binary: str) -> bytes:
    # Read exactly one named member, never extract archive paths onto the filesystem.
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if archive.getinfo(binary).file_size > MAX_BYTES:
                raise CheckFailure("Tool binary exceeds the size bound.")
            return archive.read(binary)
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        member = archive.getmember(binary)
        if not member.isfile() or member.size > MAX_BYTES:
            raise CheckFailure("Invalid tool archive member.")
        stream = archive.extractfile(member)
        if stream is None:
            raise CheckFailure("Missing tool binary.")
        return stream.read(MAX_BYTES + 1)


def get_tool(name: str, root: Path = ROOT) -> Path:
    system = platform.system().lower()
    if system not in {"windows", "linux"} or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise CheckFailure("Verification tools currently support Windows/Linux x86_64 only.")
    target = f"{system}-x86_64"
    manifest = json.loads((root / "scripts/tools.json").read_text(encoding="utf-8"))
    spec = manifest[name]
    version = spec["version"]
    if spec["repository"] != REPOSITORIES[name] or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise CheckFailure("Invalid tool release pin.")
    pin = spec["platforms"][target]
    asset = pin["asset"]
    if Path(asset).name != asset or not asset.startswith(f"{name}_{version}_"):
        raise CheckFailure("Invalid tool asset name.")
    binary = name + (".exe" if system == "windows" else "")
    destination = root / ".cache/check-tools" / f"{name}-{version}" / target / binary
    destination.resolve().relative_to(root.resolve())
    if destination.is_symlink():
        raise CheckFailure("Tool cache must not contain a symbolic link.")
    if destination.exists():
        verify_hash(destination.read_bytes(), pin["binary_sha256"])
        return destination

    url = f"https://github.com/{spec['repository']}/releases/download/v{version}/{asset}"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            if not response.url.startswith("https://"):
                raise CheckFailure("Tool download requires HTTPS.")
            payload = response.read(MAX_BYTES + 1)
    except OSError:
        raise CheckFailure("Tool download failed; verification is incomplete.") from None
    if len(payload) > MAX_BYTES:
        raise CheckFailure("Tool archive exceeds the size bound.")
    verify_hash(payload, pin["archive_sha256"])
    executable = extract_binary(payload, asset, binary)
    verify_hash(executable, pin["binary_sha256"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".download")
    temporary.write_bytes(executable)
    temporary.chmod(0o700)
    temporary.replace(destination)
    return destination
