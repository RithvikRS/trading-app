"""Docker lifecycle for isolated local databases; never accepts remote service URLs."""

import csv
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import URL

from trading_db.bootstrap import provision
from trading_db.connections import DatabaseFailure, Role

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache/postgres"
ROLES: tuple[Role, ...] = ("bootstrap", "migrator", "runtime")


def execute(command: list[str], *, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            env=env,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        raise DatabaseFailure(
            "Local database tool could not complete; check Docker locally."
        ) from None
    if result.returncode:
        raise DatabaseFailure("Local database tool failed; check Docker locally.")
    return result.stdout.strip()


def local_context() -> str:
    if any(key in os.environ for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY")):
        raise DatabaseFailure("Remove Docker endpoint overrides; a local context is required.")
    name = execute(["docker", "context", "show"])
    endpoint = execute(
        ["docker", "context", "inspect", name, "--format", "{{.Endpoints.docker.Host}}"]
    )
    if not endpoint.startswith(("unix:///", "npipe:////./pipe/")):
        raise DatabaseFailure("The selected Docker context must use a local socket.")
    version = execute(["docker", "--context", name, "version", "--format", "{{.Server.Version}}"])
    if not re.match(r"^\d+\.", version) or int(version.split(".")[0]) < 28:
        raise DatabaseFailure("Docker Engine 28 or newer is required for loopback port isolation.")
    return name


def private_directory(path: Path) -> None:
    path.resolve().relative_to(ROOT.resolve())
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        identity = next(csv.reader([execute(["whoami", "/user", "/fo", "csv", "/nh"])]))[1]
        if not re.fullmatch(r"S-[0-9-]+", identity):
            raise DatabaseFailure("Cannot establish private credential-file permissions.")
        execute(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{identity}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            ]
        )
    else:
        path.chmod(0o700)


@dataclass(frozen=True)
class LocalService:
    kind: Literal["development", "test"]
    project: str
    directory: Path
    context: str

    @property
    def database(self) -> str:
        return "trading_dev" if self.kind == "development" else "trading_test"

    def initialize(self) -> None:
        private_directory(self.directory)
        (self.directory / "project.json").write_text(
            json.dumps({"project": self.project, "kind": self.kind}), encoding="utf-8"
        )
        paths = [self.directory / role for role in ROLES]
        present = [path.exists() for path in paths]
        if any(present) and not all(present):
            raise DatabaseFailure("Incomplete local credentials; restore the original files.")
        if not any(present):
            for path in paths:
                # Exclusive creation prevents replacing an existing local credential.
                with path.open("x", encoding="ascii") as stream:
                    stream.write(secrets.token_hex(32))
                path.chmod(0o600)
        for role in ROLES:
            self.password(role)
        (self.directory / "compose.env").write_text("", encoding="ascii")

    def password(self, role: Role) -> str:
        path = self.directory / role
        if path.is_symlink() or path.resolve().parent != self.directory.resolve():
            raise DatabaseFailure("Invalid local credential path.")
        value = path.read_text(encoding="ascii")
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise DatabaseFailure("Invalid local credential file.")
        return value

    def compose(self, *args: str) -> str:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("COMPOSE_", "TRADING_DB_"))
        }
        environment.update(
            {
                "TRADING_DB_NAME": self.database,
                "TRADING_DB_PROJECT": self.project,
                "TRADING_DB_SECRET_FILE": str(self.directory / "bootstrap"),
            }
        )
        return execute(
            [
                "docker",
                "--context",
                self.context,
                "compose",
                "--project-name",
                self.project,
                "--project-directory",
                str(ROOT),
                "--env-file",
                str(self.directory / "compose.env"),
                "-f",
                str(ROOT / "infra/postgres/compose.yaml"),
                "-f",
                str(ROOT / f"infra/postgres/{self.kind}.yaml"),
                *args,
            ],
            env=environment,
        )

    def url(self, role: Role) -> URL:
        address = self.compose("port", "postgres", "5432")
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]{4,5}", address):
            raise DatabaseFailure("Database is not published exclusively on IPv4 loopback.")
        return URL.create(
            "postgresql+psycopg",
            username=f"trading_{role}",
            password=self.password(role),
            host="127.0.0.1",
            port=int(address.split(":")[1]),
            database=self.database,
        )

    def up(self) -> None:
        self.initialize()
        self.compose("up", "--detach", "--wait", "--wait-timeout", "90", "postgres")
        provision(
            self.url("bootstrap"), {role: self.password(role) for role in ROLES}, self.project
        )

    def down(self) -> None:
        expected = (
            self.project == "trading-development"
            if self.kind == "development"
            else bool(re.fullmatch(r"trading-test-[0-9a-f]{16}", self.project))
        )
        if not expected:
            raise DatabaseFailure("Refusing cleanup of an unknown database project.")
        # Development volumes are deliberately retained; tests have tmpfs only.
        self.compose("down", "--timeout", "10")

    def write_test_context(self) -> Path:
        if self.kind != "test":
            raise DatabaseFailure("Only a disposable service may provide test credentials.")
        path = self.directory / "context.json"
        path.write_text(
            json.dumps(
                {
                    "project": self.project,
                    "port": self.url("migrator").port,
                }
            ),
            encoding="utf-8",
        )
        return path


def development() -> LocalService:
    return LocalService(
        "development", "trading-development", CACHE / "development", local_context()
    )


@contextmanager
def disposable() -> Iterator[LocalService]:
    context = local_context()
    private_directory(CACHE / "tests")
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=CACHE / "tests"))
    service = LocalService("test", f"trading-test-{secrets.token_hex(8)}", directory, context)
    try:
        service.up()
        yield service
    finally:
        # Retain credentials if Docker cannot stop the service, allowing local recovery.
        service.down()
        directory.resolve().relative_to((CACHE / "tests").resolve())
        if directory.is_symlink():
            raise DatabaseFailure("Refusing cleanup of a linked test credential directory.")
        shutil.rmtree(directory)
