"""Exact local build inputs and a synthetic test of Docker's context filtering."""

import re
import stat
import subprocess
from pathlib import Path

from scripts.tooling import CheckFailure

MANIFEST = "infra/application/build-context.txt"
FIXED_INPUTS = frozenset(
    {
        "backend/pyproject.toml",
        "backend/uv.lock",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/workspace.config.ts",
        "frontend/workspace-boundary.ts",
        "frontend/src/design.css",
        "frontend/workspace/index.html",
        "infra/application/Dockerfile",
    }
)
SOURCE_DIRECTORIES = {
    "backend/trading_api": {".py"},
    "backend/trading_auth": {".py"},
    "backend/trading_db": {".py"},
    "backend/trading_connectors": {".py"},
    "frontend/workspace/src": {".ts", ".tsx", ".css"},
}
PROBE_DOCKERFILE = "FROM scratch\nCOPY . /context/\nCOPY backend/trading_connectors /connectors/\n"
SYNTHETIC_INPUT = b"synthetic allowed build input\n"
SYNTHETIC_EXCLUDED = b"synthetic excluded build input\n"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def allowed_input(name: str) -> bool:
    """Only literal paths under the reviewed, shallow production source layout."""
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", name):
        return False
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    if name in FIXED_INPUTS:
        return True
    parent, _, basename = name.rpartition("/")
    return (
        parent in SOURCE_DIRECTORIES
        and not basename.startswith(".")
        and Path(basename).suffix in SOURCE_DIRECTORIES[parent]
    )


def regular_input(root: Path, name: str) -> None:
    """Inspect metadata without following links, including Windows junctions."""
    path = root
    parts = ("", *name.split("/"))
    try:
        for index, part in enumerate(parts):
            if part:
                path = path / part
            metadata = path.lstat()
            linked = stat.S_ISLNK(metadata.st_mode) or bool(
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
            expected_kind = stat.S_ISREG if index == len(parts) - 1 else stat.S_ISDIR
            require(
                not linked
                and expected_kind(metadata.st_mode)
                and (index < len(parts) - 1 or metadata.st_nlink == 1),
                "Build files need one hard link, regular type, and unlinked directory ancestors.",
            )
    except OSError:
        raise CheckFailure("A required build input is unavailable.") from None


def tracked_inputs(root: Path) -> frozenset[str]:
    """Read the local Git index; never infer tracked membership from the filesystem."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--stage", "-z"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=15,
            check=False,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        raise CheckFailure("Build input tracking could not be verified.") from None
    require(result.returncode == 0, "Build input tracking could not be verified.")
    selected = set()
    for entry in result.stdout.split("\0"):
        if not entry:
            continue
        header, separator, name = entry.partition("\t")
        require(bool(separator), "Invalid Git build input inventory.")
        if not allowed_input(name):
            continue
        fields = header.split()
        require(
            len(fields) == 3 and fields[0] in {"100644", "100755"} and fields[2] == "0",
            "Build inputs must be regular, conflict-free tracked files.",
        )
        require(name not in selected, "Duplicate Git build input inventory.")
        selected.add(name)
    require(FIXED_INPUTS <= selected, "A fixed build input is not tracked.")
    return frozenset(selected)


def ignore_text(paths: tuple[str, ...]) -> str:
    # Docker matches parent directories too. A literal filename exception must
    # not admit descendants if that filename is replaced with a directory.
    return "**\n" + "".join(f"!{name}\n{name}/**\n" for name in paths)


def validate_build_context(root: Path) -> tuple[str, ...]:
    for name in (MANIFEST, ".dockerignore"):
        regular_input(root, name)
    try:
        paths = tuple((root / MANIFEST).read_text(encoding="utf-8").splitlines())
        actual_ignore = (root / ".dockerignore").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise CheckFailure("Build input policy is unavailable.") from None
    require(
        bool(paths)
        and paths == tuple(sorted(set(paths)))
        and all(allowed_input(name) for name in paths),
        "Build input manifest must contain sorted unique literal production file paths.",
    )
    require(
        frozenset(paths) == tracked_inputs(root),
        "Build input manifest differs from tracked production inputs; review and update it.",
    )
    require(
        actual_ignore == ignore_text(paths), "Build ignore rules differ from the exact manifest."
    )
    # A Dockerfile-specific ignore file would silently replace the root policy.
    override = root / "infra/application/Dockerfile.dockerignore"
    try:
        override.lstat()
    except FileNotFoundError:
        pass
    except OSError:
        raise CheckFailure("Build ignore override could not be checked.") from None
    else:
        raise CheckFailure("Build ignore override is forbidden.")
    for name in paths:
        regular_input(root, name)
    return paths


def synthetic_exclusions() -> tuple[str, ...]:
    names = {
        ".git/config",
        ".cache/private.txt",
        ".env",
        "backend/.env",
        "backend/.venv/ignored.py",
        "backend/tests/fixture.py",
        "frontend/.env",
        "frontend/node_modules/ignored.js",
        "frontend/src/fixtures/private.ts",
        "frontend/workspace/dist/index.html",
        "infra/private.txt",
        "infra/application/private.pem",
    }
    for parent, suffixes in SOURCE_DIRECTORIES.items():
        names.update(
            {
                f"{parent}/.env",
                f"{parent}/private.txt",
                f"{parent}/__pycache__/ignored.pyc",
                f"{parent}/nested/private.txt",
            }
        )
        for suffix in suffixes:
            names.add(f"{parent}/untracked-probe{suffix}")
            names.add(f"{parent}/directory-probe{suffix}/private.txt")
    return tuple(sorted(names))


def validate_context_export(export: Path, expected: dict[str, bytes]) -> None:
    actual = set()
    for path in export.rglob("*"):
        relative = path.relative_to(export).as_posix()
        metadata = path.lstat()
        require(
            not stat.S_ISLNK(metadata.st_mode)
            and not (
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ),
            "Synthetic context export contains a linked entry.",
        )
        if stat.S_ISDIR(metadata.st_mode):
            continue
        require(
            stat.S_ISREG(metadata.st_mode), "Synthetic context export contains a special entry."
        )
        actual.add(relative)
        require(
            relative in expected
            and metadata.st_size == len(expected[relative])
            and path.read_bytes() == expected[relative],
            "Synthetic context exported an unexpected or changed input.",
        )
    require(actual == set(expected), "Synthetic context omitted a required input.")


def verify_build_context(root: Path, directory: Path, docker: list[str], run) -> None:
    """Exercise actual Docker filtering without sending repository file contents."""
    require(
        len(docker) == 3 and docker[:2] == ["docker", "--context"],
        "Synthetic context verification requires an explicit local Docker context.",
    )
    paths = validate_build_context(root)
    context = directory / "context-fixture"
    export = directory / "context-export"
    context.mkdir()
    expected = {}
    for name in paths:
        target = context / name
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            PROBE_DOCKERFILE.encode() if name == "infra/application/Dockerfile" else SYNTHETIC_INPUT
        )
        target.write_bytes(payload)
        expected[f"context/{name}"] = payload
        if name.startswith("backend/trading_connectors/"):
            expected[f"connectors/{Path(name).name}"] = payload
    (context / ".dockerignore").write_text(ignore_text(paths), encoding="utf-8")
    for name in synthetic_exclusions():
        require(name not in paths, "Synthetic sentinel overlaps an allowed build input.")
        target = context / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(SYNTHETIC_EXCLUDED)
    run(
        [
            *docker,
            "buildx",
            "build",
            "--builder",
            docker[2],
            "--network=none",
            "--no-cache",
            "--provenance=false",
            "--output",
            f"type=local,dest={export}",
            "--file",
            str(context / "infra/application/Dockerfile"),
            str(context),
        ],
        timeout=120,
    )
    validate_context_export(export, expected)
