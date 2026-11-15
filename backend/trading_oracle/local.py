"""Disposable Oracle container custody, restricted to a verified local Docker daemon."""

import base64
import csv
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache" / "oracle"
IMAGE = (
    "container-registry.oracle.com/database/free:23.26.3.0@sha256:"
    "f988b0c04c4c386cd306a2a914c0d7a9702d83acc31b064a28ad8eb6278a8fba"
)
LABEL = "com.trading.oracle.run"
WORKSPACE = hashlib.sha256(str(ROOT).encode()).hexdigest()
RUN_ID = re.compile(r"[0-9a-f]{32}")
MEMORY = 3 * 1024**3
SHM = 1024**3
PIDS = 512
NETWORK_OPTIONS = {
    "com.docker.network.bridge.host_binding_ipv4": "127.0.0.1",
    "com.docker.network.bridge.enable_icc": "false",
}


class OracleFailure(ValueError):
    """Only fixed diagnostics may cross the local verification boundary."""


def guarded(path: Path, *, file: bool = False) -> Path:
    """Reject escapes and every existing link/reparse component inside this checkout."""
    try:
        path.relative_to(ROOT)
        if path.resolve() != path:
            raise OracleFailure("Oracle verification paths must not be linked.")
        for item in (path, *path.parents):
            if item.exists() or item.is_symlink():
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise OracleFailure("Oracle verification paths must not be linked.")
                if item == path and file and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                    raise OracleFailure(
                        "Oracle verification file is not an exclusive regular file."
                    )
            if item == ROOT:
                break
    except (OSError, ValueError) as error:
        if isinstance(error, OracleFailure):
            raise
        raise OracleFailure("Oracle verification path is invalid.") from None
    return path


def execute(
    args: list[str], *, timeout: float = 30, payload: str | None = None, required: bool = True
) -> str:
    try:
        result = subprocess.run(
            args,
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        raise OracleFailure("Oracle verification tool did not complete.") from None
    if len(result.stdout) > 131072 or len(result.stderr) > 131072:
        raise OracleFailure("Oracle verification tool returned excessive output.")
    if result.returncode:
        if required:
            raise OracleFailure("Oracle verification tool failed.")
        return ""
    return result.stdout.strip()


def private_directory(path: Path) -> None:
    try:
        path.relative_to(CACHE)
    except ValueError:
        raise OracleFailure("Oracle permissions are restricted to its private cache.") from None
    guarded(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    guarded(path)
    if os.name == "nt":
        identity = next(csv.reader([execute(["whoami", "/user", "/fo", "csv", "/nh"])]))[1]
        if not re.fullmatch(r"S-[0-9-]+", identity):
            raise OracleFailure("Cannot establish private Oracle file permissions.")
        # Replace the whole DACL in one operation: grant:r alone retains unrelated ACEs.
        quoted = str(path).replace("'", "''")
        script = (
            "$ErrorActionPreference='Stop';"
            "$PSModuleAutoLoadingPreference='None';"
            f"$directory='{quoted}';$sid='{identity}';"
            "$acl=[System.IO.Directory]::GetAccessControl($directory);"
            "$owner=$acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value;"
            "if($owner -notin @($sid,'S-1-5-18')){throw 'OWNER'};"
            "$acl.SetSecurityDescriptorSddlForm("
            "('D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;'+$sid+')'),"
            "[System.Security.AccessControl.AccessControlSections]::Access);"
            "[System.IO.Directory]::SetAccessControl($directory,$acl);"
            "$actual=[System.IO.Directory]::GetAccessControl($directory);"
            "if($actual.GetOwner([System.Security.Principal.SecurityIdentifier]).Value "
            "-ne $owner){throw 'OWNER'};"
            "$rules=@($actual.GetAccessRules($true,$true,"
            "[System.Security.Principal.SecurityIdentifier]));"
            "if(-not $actual.AreAccessRulesProtected -or $rules.Count -ne 2){throw 'ACL'};"
            "$seen=@();foreach($rule in $rules){"
            "if($rule.IsInherited -or $rule.AccessControlType -ne 'Allow' -or "
            "$rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::"
            "FullControl -or $rule.InheritanceFlags -ne "
            "([System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor "
            "[System.Security.AccessControl.InheritanceFlags]::ObjectInherit) -or "
            "$rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None)"
            "{throw 'ACL'};$seen+=$rule.IdentityReference.Value};"
            "if($seen[0] -eq $seen[1] -or "
            "$sid -notin $seen -or 'S-1-5-18' -notin $seen){throw 'ACL'};"
            "[System.Console]::Out.WriteLine('ORACLE_PRIVATE_DIRECTORY')"
        )
        result = execute(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                base64.b64encode(script.encode("utf-16-le")).decode("ascii"),
            ]
        )
        if result != "ORACLE_PRIVATE_DIRECTORY":
            raise OracleFailure("Cannot establish private Oracle file permissions.")
    else:
        path.chmod(0o700)
    guarded(path)


def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Oracle manifest field.")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    guarded(path, file=True)
    try:
        raw = path.read_bytes()
        if len(raw) > 8192:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=unique_fields)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except OSError, ValueError:
        raise OracleFailure("Oracle run manifest is invalid.") from None


def write_json(path: Path, value: dict[str, Any]) -> None:
    guarded(path, file=True)
    temporary = guarded(path.with_suffix(".new"), file=True)
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def exclusive() -> Iterator[None]:
    private_directory(CACHE)
    lock = guarded(CACHE / "verification.lock", file=True)
    with lock.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise OracleFailure("Another Oracle verification or cleanup is active.") from None
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def local_context() -> str:
    if any(key in os.environ for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY")):
        raise OracleFailure("Oracle verification requires an unmodified local Docker context.")
    if any(
        key.startswith(("ORACLE_", "TNS_", "NLS_")) or key in {"TWO_TASK", "LOCAL", "ORA_SDTZ"}
        for key in os.environ
    ):
        raise OracleFailure("Remove ambient Oracle connection settings before verification.")
    context = execute(["docker", "context", "show"])
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", context):
        raise OracleFailure("Oracle verification Docker context is invalid.")
    endpoint = execute(
        ["docker", "context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}"]
    )
    if not endpoint.startswith(("unix:///", "npipe:////./pipe/")):
        raise OracleFailure("Oracle verification requires a local Docker socket.")
    details = execute(
        [
            "docker",
            "--context",
            context,
            "info",
            "--format",
            "{{.OSType}}|{{.ServerVersion}}|{{.MemTotal}}",
        ]
    )
    parts = details.split("|")
    if len(parts) != 3 or parts[0] != "linux" or not re.fullmatch(r"[0-9]+\.[0-9.]+.*", parts[1]):
        raise OracleFailure("Oracle verification requires a local Linux Docker engine.")
    if int(parts[1].split(".")[0]) < 28 or not parts[2].isdigit() or int(parts[2]) < MEMORY:
        raise OracleFailure("Oracle verification requires Docker 28 and sufficient memory.")
    return context


def run_directory(run_id: str) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise OracleFailure("Oracle cleanup requires an exact generated run identifier.")
    return guarded(CACHE / "runs" / run_id)


def password(directory: Path, name: str) -> str:
    if name not in {"oracle_pwd", "smoke_pwd"}:
        raise OracleFailure("Unknown Oracle secret purpose.")
    path = guarded(directory / name, file=True)
    try:
        value = path.read_text(encoding="ascii")
    except OSError:
        raise OracleFailure("Oracle run secret is unavailable.") from None
    if not re.fullmatch(r"Ta1[0-9a-f]{48}", value):
        raise OracleFailure("Oracle run secret is invalid.")
    return value


class LocalRun:
    def __init__(self, run_id: str, context: str) -> None:
        self.run_id = run_id
        self.directory = run_directory(run_id)
        self.context = context
        self.name = f"trading-oracle-test-{run_id}"
        self.manifest = self.directory / "manifest.json"
        self.created = False

    def docker(self, *args: str, **kwargs: Any) -> str:
        return execute(["docker", "--context", self.context, *args], **kwargs)

    def initialize(self) -> None:
        private_directory(CACHE / "runs")
        # Atomic creation must succeed before this process owns cleanup authority.
        self.directory.mkdir(mode=0o700)
        self.created = True
        private_directory(self.directory)
        write_json(
            self.manifest,
            {
                "format": 1,
                "run_id": self.run_id,
                "context": self.context,
                "workspace": WORKSPACE,
                "image": IMAGE,
                "status": "prepared",
                "outcome": "pending",
                "image_id": None,
                "container_id": None,
                "network_id": None,
            },
        )
        private_directory(self.directory / "config")
        for name in ("oracle_pwd", "smoke_pwd"):
            with guarded(self.directory / name, file=True).open("x", encoding="ascii") as stream:
                stream.write("Ta1" + secrets.token_hex(24))
            if os.name != "nt":
                # Private 0700 host parent; only this mounted file is readable by oracle UID.
                (self.directory / name).chmod(0o444 if name == "oracle_pwd" else 0o600)

    def validate_manifest(self) -> dict[str, Any]:
        value = read_json(self.manifest)
        if type(value.get("format")) is not int:
            raise OracleFailure("Oracle run format is invalid.")
        if (
            set(value)
            != {
                "format",
                "run_id",
                "context",
                "workspace",
                "image",
                "status",
                "outcome",
                "image_id",
                "container_id",
                "network_id",
            }
            or (
                value["format"],
                value["run_id"],
                value["context"],
                value["workspace"],
                value["image"],
            )
            != (1, self.run_id, self.context, WORKSPACE, IMAGE)
            or value["status"] not in {"prepared", "started", "passed", "failed", "cleaned"}
        ):
            raise OracleFailure("Oracle run ownership manifest does not match.")
        if value["outcome"] not in {"pending", "passed", "failed"}:
            raise OracleFailure("Oracle run result is invalid.")
        for kind in ("image", "container", "network"):
            identity = value[kind + "_id"]
            pattern = r"sha256:[0-9a-f]{64}" if kind == "image" else r"[0-9a-f]{64}"
            if identity is not None and (
                type(identity) is not str or not re.fullmatch(pattern, identity)
            ):
                raise OracleFailure("Oracle resource manifest is invalid.")
        return value

    def record_resource(self, kind: str, identity: str) -> None:
        value = self.validate_manifest()
        key = kind + "_id"
        if kind not in {"image", "container", "network"} or value[key] not in {None, identity}:
            raise OracleFailure("Oracle resource identity changed.")
        pattern = r"sha256:[0-9a-f]{64}" if kind == "image" else r"[0-9a-f]{64}"
        if not re.fullmatch(pattern, identity):
            raise OracleFailure("Oracle resource identity is invalid.")
        value[key] = identity
        write_json(self.manifest, value)

    def mark(self, status: str) -> None:
        value = self.validate_manifest()
        value["status"] = status
        if status in {"passed", "failed"}:
            value["outcome"] = status
        write_json(self.manifest, value)

    def resources(self, kind: str) -> list[str]:
        if kind == "container":
            args = (
                "ps",
                "--all",
                "--no-trunc",
                "--filter",
                f"name=^/{self.name}$",
                "--format",
                "{{.ID}}",
            )
        else:
            args = (
                "network",
                "ls",
                "--no-trunc",
                "--filter",
                f"name=^{self.name}$",
                "--format",
                "{{.ID}}",
            )
        values = self.docker(*args).splitlines()
        if len(values) > 1 or any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in values):
            raise OracleFailure("Oracle run resource identity is ambiguous.")
        expected = self.validate_manifest()[kind + "_id"]
        if values and expected is not None and values != [expected]:
            raise OracleFailure("Oracle resource was replaced.")
        return values

    def inspect(self, kind: str, identity: str, *, custody_only: bool = False) -> dict[str, Any]:
        try:
            value = json.loads(self.docker(kind, "inspect", identity, "--format", "{{json .}}"))
            if not isinstance(value, dict):
                raise ValueError
            labels = value.get("Labels") if kind == "network" else value["Config"].get("Labels")
            if (
                not isinstance(labels, dict)
                or labels.get(LABEL) != self.run_id
                or (labels.get("com.trading.oracle.workspace") != WORKSPACE)
            ):
                raise ValueError
            manifest = self.validate_manifest()
            if value["Id"] != identity or manifest[kind + "_id"] not in {None, identity}:
                raise ValueError
            if kind == "container" and (
                value["Config"]["Image"] != IMAGE or value["Image"] != manifest["image_id"]
            ):
                raise ValueError
            name = value["Name"]
            if name != (self.name if kind == "network" else "/" + self.name):
                raise ValueError
            if custody_only:
                return value
            if kind == "network":
                if (
                    value["Driver"] != "bridge"
                    or value["Internal"] is not False
                    or value["EnableIPv4"] is not True
                    or value["EnableIPv6"] is not False
                    or value["Options"] != NETWORK_OPTIONS
                ):
                    raise ValueError
            else:
                self.validate_container(value)
            return value
        except KeyError, TypeError, ValueError:
            raise OracleFailure("Oracle run resource does not match its custody profile.") from None

    def validate_container(self, value: dict[str, Any]) -> None:
        host = value["HostConfig"]
        mounts = value["Mounts"]
        if value["Config"]["Image"] != IMAGE or value["Config"]["User"] != "oracle":
            raise ValueError
        image_id = self.docker("image", "inspect", IMAGE, "--format", "{{.Id}}")
        if value["Image"] != image_id:
            raise ValueError
        if (
            host["Privileged"]
            or host["NetworkMode"] != self.name
            or (
                host["Memory"],
                host["MemorySwap"],
                host["NanoCpus"],
                host["ShmSize"],
                host["PidsLimit"],
            )
            != (MEMORY, MEMORY, 2_000_000_000, SHM, PIDS)
        ):
            raise ValueError
        if host["LogConfig"]["Type"] != "none" or host["RestartPolicy"]["Name"] != "no":
            raise ValueError
        if (
            host["CapDrop"] != ["ALL"]
            or host["CapAdd"]
            or (host["SecurityOpt"] != ["no-new-privileges"])
        ):
            raise ValueError
        if (
            len(mounts) != 1
            or mounts[0]["Type"] != "bind"
            or mounts[0]["RW"]
            or (
                mounts[0]["Destination"] != "/run/secrets/oracle_pwd"
                or Path(mounts[0]["Source"]) != guarded(self.directory / "oracle_pwd", file=True)
            )
        ):
            raise ValueError
        ports = host["PortBindings"]
        if (
            set(ports) != {"1521/tcp"}
            or len(ports["1521/tcp"]) != 1
            or (ports["1521/tcp"][0]["HostIp"] != "127.0.0.1")
        ):
            raise ValueError
        if set(value["NetworkSettings"]["Networks"]) != {self.name}:
            raise ValueError

    def ensure_image(self) -> None:
        image_id = self.docker("image", "inspect", IMAGE, "--format", "{{.Id}}", required=False)
        if not image_id:
            self.docker("pull", "--quiet", IMAGE, timeout=600)
            image_id = self.docker("image", "inspect", IMAGE, "--format", "{{.Id}}")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise OracleFailure("Pinned Oracle image identity is invalid.")
        digests = json.loads(
            self.docker("image", "inspect", IMAGE, "--format", "{{json .RepoDigests}}")
        )
        expected = IMAGE.split(":23.26.3.0", 1)[0] + "@" + IMAGE.split("@", 1)[1]
        if not isinstance(digests, list) or expected not in digests:
            raise OracleFailure("Pinned Oracle image digest was not retained.")
        self.record_resource("image", image_id)

    def start(self) -> None:
        self.validate_manifest()
        if self.resources("container") or self.resources("network"):
            raise OracleFailure("Oracle run resources already exist.")
        self.ensure_image()
        labels = (
            "--label",
            f"{LABEL}={self.run_id}",
            "--label",
            f"com.trading.oracle.workspace={WORKSPACE}",
        )
        network_id = self.docker(
            "network",
            "create",
            "--driver",
            "bridge",
            "--ipv4=true",
            "--ipv6=false",
            "--opt",
            "com.docker.network.bridge.host_binding_ipv4=127.0.0.1",
            "--opt",
            "com.docker.network.bridge.enable_icc=false",
            *labels,
            self.name,
        )
        self.record_resource("network", network_id)
        self.inspect("network", network_id)
        container_id = self.docker(
            "create",
            "--pull=never",
            "--name",
            self.name,
            *labels,
            "--network",
            self.name,
            "--publish",
            "127.0.0.1::1521",
            "--memory",
            str(MEMORY),
            "--memory-swap",
            str(MEMORY),
            "--cpus",
            "2",
            "--shm-size",
            str(SHM),
            "--pids-limit",
            str(PIDS),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--log-driver",
            "none",
            "--mount",
            f"type=bind,source={self.directory / 'oracle_pwd'},"
            "target=/run/secrets/oracle_pwd,readonly",
            IMAGE,
        )
        self.record_resource("container", container_id)
        self.inspect("container", container_id)
        self.docker("start", self.name)
        self.mark("started")

    def port(self) -> int:
        ids = self.resources("container")
        if not ids:
            raise OracleFailure("Oracle verification container is unavailable.")
        value = self.inspect("container", ids[0])
        ports = value["NetworkSettings"]["Ports"]
        if not value["State"]["Running"] or set(ports) != {"1521/tcp"}:
            raise OracleFailure("Oracle verification listener is unavailable.")
        binding = ports["1521/tcp"]
        if (
            not isinstance(binding, list)
            or len(binding) != 1
            or binding[0]["HostIp"] != "127.0.0.1"
        ):
            raise OracleFailure("Oracle verification listener is not exclusively local.")
        port = binding[0]["HostPort"]
        if not isinstance(port, str) or not port.isdigit() or not 1024 <= int(port) <= 65535:
            raise OracleFailure("Oracle verification listener port is invalid.")
        return int(port)

    def sql(self, statement: str, *, required: bool = True) -> str:
        return self.docker(
            "exec",
            "--interactive",
            self.name,
            "sqlplus",
            "-s",
            "/",
            "as",
            "sysdba",
            payload="WHENEVER OSERROR EXIT FAILURE\nWHENEVER SQLERROR EXIT FAILURE ROLLBACK\n"
            "SET ECHO OFF FEEDBACK OFF HEADING OFF VERIFY OFF PAGESIZE 0\n"
            + statement
            + "\nEXIT\n",
            timeout=15,
            required=required,
        )

    def bootstrap(self) -> None:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            self.port()
            if (
                self.sql(
                    "SELECT 'TRADING_READY' FROM v$pdbs WHERE name = 'FREEPDB1' "
                    "AND open_mode = 'READ WRITE' AND restricted = 'NO';",
                    required=False,
                )
                == "TRADING_READY"
            ):
                break
            time.sleep(2)
        else:
            raise OracleFailure("Oracle verification database did not become ready.")
        self.sql(
            "ALTER SESSION SET CONTAINER=FREEPDB1;\n"
            f'CREATE USER trading_smoke IDENTIFIED BY "{password(self.directory, "smoke_pwd")}" '
            "DEFAULT TABLESPACE users QUOTA 2M ON users;\n"
            "GRANT CREATE SESSION, CREATE TABLE TO trading_smoke;\n"
            "CREATE TABLE trading_smoke.run_marker (marker VARCHAR2(32 BYTE) NOT NULL);\n"
            f"INSERT INTO trading_smoke.run_marker VALUES ('{self.run_id}');\nCOMMIT;"
        )

    def probe(self) -> None:
        payload = json.dumps({"run_id": self.run_id, "port": self.port()})
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
        }
        environment["ORA_SDTZ"] = "UTC"
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-S", str(ROOT / "backend/trading_oracle/probe.py")],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=90,
                check=False,
            )
        except OSError, subprocess.TimeoutExpired:
            raise OracleFailure("Oracle verification probe did not complete.") from None
        if result.returncode or result.stdout.strip() != "ORACLE_SMOKE_PASSED" or result.stderr:
            raise OracleFailure("Oracle verification probe failed.")

    def cleanup(self) -> None:
        self.validate_manifest()
        container = self.resources("container")
        network = self.resources("network")
        if container:
            self.inspect("container", container[0], custody_only=True)
        if network:
            value = self.inspect("network", network[0], custody_only=True)
            if set(value.get("Containers", {})) - set(container):
                raise OracleFailure("Oracle network contains an unrelated container.")
        if container:
            self.docker("rm", "--force", container[0], timeout=60)
        if network:
            self.inspect("network", network[0], custody_only=True)
            self.docker("network", "rm", network[0])
        if self.resources("container") or self.resources("network"):
            raise OracleFailure("Oracle cleanup did not remove its owned resources.")
        for name in ("oracle_pwd", "smoke_pwd"):
            target = guarded(self.directory / name, file=True)
            if target.exists():
                target.unlink()
        config = guarded(self.directory / "config")
        if config.exists():
            config.rmdir()
        self.mark("cleaned")


def verify() -> str:
    with exclusive():
        run = LocalRun(secrets.token_hex(16), local_context())
        print(f"Oracle verification run: {run.run_id}", flush=True)
        try:
            run.initialize()
            run.start()
            run.bootstrap()
            run.probe()
            run.mark("passed")
        except BaseException:
            if run.created and run.manifest.exists():
                run.mark("failed")
            raise
        finally:
            if run.created and run.manifest.exists():
                run.cleanup()
        return run.run_id


def cleanup(run_id: str) -> None:
    with exclusive():
        LocalRun(run_id, local_context()).cleanup()
