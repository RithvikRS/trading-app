"""Run the same fail-closed checks locally and on disposable CI runners."""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote

# Direct script invocation works without installing a project package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.tooling import ROOT, CheckFailure, get_tool  # noqa: E402


def run(label: str, command: list[str], cwd: Path = ROOT, quiet: bool = False) -> str:
    print(f"Checking {label}...", flush=True)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1200,
            stdout=subprocess.PIPE if quiet else None,
            stderr=subprocess.PIPE if quiet else None,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise CheckFailure(f"{label} could not complete.") from None
    if result.returncode:
        # Scanner output may contain source snippets even when a new detector misbehaves.
        raise CheckFailure(f"{label} failed (exit {result.returncode}).")
    return result.stdout or ""


def uv_command() -> str:
    local = ROOT / ".cache/api-tools" / ("Scripts/uv.exe" if os.name == "nt" else "bin/uv")
    command = str(local) if local.is_file() else shutil.which("uv")
    if command is None:
        raise CheckFailure("Install the pinned uv using docs/development.md first.")
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))
    version = project["tool"]["uv"]["required-version"].removeprefix("==")
    if run("uv version", [command, "--version"], quiet=True).split()[1] != version:
        raise CheckFailure(f"Use uv {version}; tool versions are pinned.")
    os.environ.setdefault("UV_CACHE_DIR", str(ROOT / ".cache/uv"))
    os.environ.setdefault("UV_PYTHON_INSTALL_DIR", str(ROOT / ".cache/python"))
    return command


def sync_backend(uv: str) -> None:
    run("locked Python installation", [uv, "sync", "--locked"], ROOT / "backend")


def backend() -> None:
    uv = uv_command()
    sync_backend(uv)
    prefix = [uv, "run", "--locked", "--no-sync"]
    for label, command in [
        ("Python lint", ["ruff", "check", ".", "../scripts"]),
        ("Python formatting", ["ruff", "format", "--check", ".", "../scripts"]),
        ("Python types", ["mypy"]),
        ("API tests", ["pytest"]),
        (
            "Python dependency advisories",
            ["python", "-m", "pip_audit", "--strict", "--progress-spinner", "off"],
        ),
    ]:
        run(label, prefix + command, ROOT / "backend")


def frontend() -> None:
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not node or not npm:
        raise CheckFailure("Install the pinned Node/npm versions from docs/verification.md.")
    expected = (ROOT / "frontend/.node-version").read_text().strip()
    if run("Node version", [node, "--version"], quiet=True).strip() != f"v{expected}":
        raise CheckFailure(f"Use Node {expected}; tool versions are pinned.")
    import json

    package = json.loads((ROOT / "frontend/package.json").read_text())
    if (
        run("npm version", [npm, "--version"], quiet=True).strip()
        != package["packageManager"].split("@")[1]
    ):
        raise CheckFailure("npm version differs from frontend/package.json.")
    for label, args in [
        ("locked frontend installation", ["ci", "--ignore-scripts", "--no-audit", "--no-fund"]),
        ("frontend tests, types, and build", ["run", "check"]),
        ("frontend dependency advisories", ["audit", "--audit-level=low", "--include=dev"]),
    ]:
        run(label, [npm, *args], ROOT / "frontend")


@contextmanager
def scratch(root: Path = ROOT):
    parent = root / ".cache/verification"
    parent.resolve().relative_to(root.resolve())
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="check-", dir=parent) as directory:
        path = Path(directory).resolve()
        path.relative_to(parent.resolve())
        yield path


def source_snapshot(destination: Path, root: Path = ROOT) -> None:
    paths = run(
        "source inventory",
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        root,
        quiet=True,
    )
    for name in set(paths.split("\0")) - {""}:
        path = root / name
        path.resolve().relative_to(root.resolve())
        if path.is_symlink():
            raise CheckFailure("Review symbolic links before scanning the source snapshot.")
        if not path.exists():
            continue  # A working-tree deletion is still covered by the history scan.
        if not path.is_file():
            raise CheckFailure("Unsupported source entry; scan cannot complete.")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def scan(secrets: Path, mode: str, target: Path, extra: list[str] | None = None) -> None:
    run(
        f"secret scan ({mode})",
        [
            str(secrets),
            mode,
            str(target),
            "--config",
            str(ROOT / ".gitleaks.toml"),
            "--redact=100",
            "--no-banner",
            "--ignore-gitleaks-allow",
            *(extra or []),
        ],
        quiet=True,
    )


def scanner_probe(secrets: Path) -> None:
    with scratch() as folder:
        # Generated fictional detector input; never put a complete token in source/history.
        token = "gh" + "p_" + "aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4"
        (folder / "probe.txt").write_text(f"token={token}\n", encoding="utf-8")
        try:
            scan(secrets, "dir", folder)
        except CheckFailure as error:
            if "(exit 1)" not in str(error):
                raise
        else:
            raise CheckFailure("Secret scanner did not detect the synthetic positive control.")
        hooks = folder / "empty-hooks"
        hooks.mkdir()
        git = [
            "git",
            "-c",
            "user.name=Verification fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            f"core.hooksPath={hooks}",
        ]
        run("synthetic history setup", [*git, "init", "--quiet"], folder, quiet=True)
        run("synthetic history staging", [*git, "add", "probe.txt"], folder, quiet=True)
        run(
            "synthetic history commit",
            [*git, "commit", "--quiet", "-m", "test: add detector input"],
            folder,
            quiet=True,
        )
        (folder / "probe.txt").write_text("ordinary synthetic content\n", encoding="utf-8")
        run("synthetic history cleanup", [*git, "add", "probe.txt"], folder, quiet=True)
        run(
            "synthetic history commit",
            [*git, "commit", "--quiet", "-m", "test: remove detector input"],
            folder,
            quiet=True,
        )
        scan(secrets, "dir", folder)
        try:
            scan(secrets, "git", folder, ["--log-opts=--all"])
        except CheckFailure as error:
            if "(exit 1)" not in str(error):
                raise
        else:
            raise CheckFailure("Secret scanner did not detect the deleted historical control.")


def documentation_links(root: Path = ROOT) -> None:
    count = 0
    for path in [root / "README.md", *sorted((root / "docs").glob("*.md"))]:
        for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", link):
                continue
            local, _, anchor = unquote(link).partition("#")
            target = (path.parent / local).resolve() if local else path.resolve()
            target.relative_to(root.resolve())
            if not target.exists():
                raise CheckFailure(f"Broken local link in {path.name}.")
            if anchor and target.suffix == ".md":
                headings = re.findall(r"^#+\s+(.+)$", target.read_text(encoding="utf-8"), re.M)
                slugs = [
                    re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
                    for heading in headings
                ]
                if anchor not in slugs:
                    raise CheckFailure(f"Broken heading link in {path.name}.")
            count += 1
    print(f"Verified {count} local documentation links.")


def repository() -> None:
    uv = uv_command()
    sync_backend(uv)
    run(
        "verification helper tests",
        [
            uv,
            "run",
            "--project",
            "backend",
            "--locked",
            "--no-sync",
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts/tests",
            "-v",
        ],
    )
    run(
        "workflow security policy",
        [uv, "run", "--project", "backend", "--locked", "--no-sync", "python", "scripts/policy.py"],
    )
    actionlint = get_tool("actionlint")
    run("workflow syntax", [str(actionlint), "-color", "-shellcheck=", "-pyflakes="])
    documentation_links()
    secrets = get_tool("gitleaks")
    scanner_probe(secrets)
    if (
        run(
            "history completeness", ["git", "rev-parse", "--is-shallow-repository"], quiet=True
        ).strip()
        != "false"
    ):
        raise CheckFailure("Fetch complete Git history before running repository checks.")
    scan(secrets, "git", ROOT, ["--log-opts=--all"])
    with scratch() as snapshot:
        source_snapshot(snapshot)
        scan(secrets, "dir", snapshot)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=["all", "backend", "frontend", "repository"])
    args = parser.parse_args()
    phases = {"repository": repository, "backend": backend, "frontend": frontend}
    try:
        for name in phases if args.scope == "all" else [args.scope]:
            phases[name]()
    except (CheckFailure, OSError, ValueError, KeyError) as error:
        message = (
            str(error)
            if isinstance(error, CheckFailure)
            else "Check setup failed; inspect configuration locally."
        )
        print(f"FAILED: {message}", file=sys.stderr)
        return 1
    print(f"PASS: {args.scope} checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
