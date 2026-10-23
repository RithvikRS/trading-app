"""Build and verify the isolated local HTTPS package; never deploy or publish it."""

import concurrent.futures
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from trading_db.connections import DatabaseFailure  # noqa: E402
from trading_db.local import local_context, private_directory  # noqa: E402

from scripts.policy import require, validate_packaging  # noqa: E402
from scripts.tooling import CheckFailure  # noqa: E402

CACHE = ROOT / ".cache/operations"


def command(args, *, environment=None, timeout=300):
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise CheckFailure("Packaging command could not complete.") from None
    require(result.returncode == 0, "Packaging command failed; inspect Docker locally.")
    return result.stdout.strip()


def certificate(directory):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Local rehearsal")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    (directory / "certificate.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    # Docker bind secrets retain host modes. Parent is private; gateway is non-root.
    for filename in ("certificate.pem", "key.pem"):
        (directory / filename).chmod(0o444)
    context = ssl.create_default_context(cafile=str(directory / "certificate.pem"))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def request(context, path="/", *, headers=None, body=None):
    connection = HTTPSConnection("127.0.0.1", 8443, context=context, timeout=10)
    try:
        connection.request(
            "GET" if body is None else "POST", path, body=body, headers=headers or {}
        )
        response = connection.getresponse()
        payload = response.read(1_000_001)
        require(len(payload) <= 1_000_000, "Unexpected response size.")
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


def probe(context):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if request(context, "/api/v1/health/live")[0] == 200:
                break
        except OSError:
            pass
        time.sleep(1)
    else:
        raise CheckFailure("HTTPS package did not become healthy.")
    try:
        request(ssl.create_default_context())
    except ssl.SSLCertVerificationError:
        pass
    else:
        raise CheckFailure("Untrusted rehearsal certificate was accepted.")
    with socket.create_connection(("127.0.0.1", 8443), timeout=5) as connection:
        try:
            with context.wrap_socket(connection, server_hostname="untrusted.invalid"):
                raise CheckFailure("Certificate hostname mismatch was accepted.")
        except ssl.SSLCertVerificationError:
            pass
    plaintext = HTTPConnection("127.0.0.1", 8443, timeout=5)
    try:
        plaintext.request("GET", "/api/v1/health/live")
        require(plaintext.getresponse().status == 400, "Plaintext request reached the API.")
    finally:
        plaintext.close()
    status, headers, html = request(context)
    require(status == 200, "Protected shell was not served.")
    require(headers.get("Cache-Control") == "no-store", "Private responses must not be cached.")
    require(
        "unsafe-inline" not in headers.get("Content-Security-Policy", "unsafe-inline"),
        "Unsafe CSP.",
    )
    require(headers.get("Strict-Transport-Security") == "max-age=300", "TLS policy is missing.")
    require("Set-Cookie" not in headers, "Locked shell must not create a session.")
    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html.decode())
    require(len(assets) >= 2, "Protected asset references missing.")
    for path in assets:
        require(request(context, path)[0] == 200, "Protected asset failed.")
    for path in (
        "/.env",
        "/.git/config",
        "/src/main.tsx",
        "/demo",
        "/sw.js",
        "/api/v1/auth/bootstrap",
        "/api/v1/preferences",
    ):
        status, headers, _ = request(context, path)
        require(
            status == 404 and headers.get("Cache-Control") == "no-store", "Unexpected public route."
        )
    require(
        request(context, headers={"Host": "untrusted.invalid"})[0] == 400, "Host override accepted."
    )
    require(
        request(
            context, headers={"X-Forwarded-Proto": "http", "Forwarded": "host=untrusted.invalid"}
        )[0]
        == 200,
        "Proxy did not overwrite forwarding headers.",
    )
    require(
        request(context, "/api/v1/auth/login", body=b"x" * 4097)[0] == 413,
        "Oversized body reached API.",
    )
    return assets


def inspect_runtime(docker, compose, run=command):
    measured = {}
    for name, memory, cpus, pids in (
        ("api", 256, 750_000_000, 64),
        ("gateway", 64, 250_000_000, 32),
    ):
        identifier = run([*compose, "ps", "--quiet", name])
        require(bool(re.fullmatch(r"[0-9a-f]{64}", identifier)), "Unexpected container identity.")
        info = json.loads(run([*docker, "inspect", identifier]))[0]
        host = info["HostConfig"]
        require(info["Config"]["User"] == "10001:10001", "Root container is forbidden.")
        require(
            host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"], "Container privileges changed."
        )
        require(host["SecurityOpt"] == ["no-new-privileges:true"], "Privilege escalation allowed.")
        require(
            host["Memory"] == memory * 1024**2 and host["MemorySwap"] == host["Memory"],
            "Memory/swap limits changed.",
        )
        require(host["NanoCpus"] == cpus and host["PidsLimit"] == pids, "CPU/PID budget changed.")
        require(host["Ulimits"] == [{"Name": "core", "Hard": 0, "Soft": 0}], "Core dumps enabled.")
        require(not info["State"]["OOMKilled"], "Container exceeded memory budget.")
        require(
            all(not mount["RW"] for mount in info["Mounts"] if mount["Type"] != "tmpfs"),
            "Writable host mount.",
        )
        if name == "gateway":
            require(
                host["PortBindings"] == {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
                "Public gateway port.",
            )
            require(
                info["NetworkSettings"]["Ports"] == host["PortBindings"],
                "Gateway mapping did not take effect.",
            )
            for network in info["NetworkSettings"]["Networks"].values():
                network_info = json.loads(
                    run([*docker, "network", "inspect", network["NetworkID"]])
                )[0]
                require(
                    network_info["Options"].get("com.docker.network.bridge.enable_icc") == "false",
                    "Container peer traffic is enabled.",
                )
        else:
            require(
                not host["PortBindings"] and host["NetworkMode"].startswith("container:"),
                "API port exposed.",
            )
        # Test actual filesystem denial, not only Docker's configuration flag.
        run(
            [
                *docker,
                "exec",
                identifier,
                "sh",
                "-c",
                "test ! -w /app 2>/dev/null && ! touch /unexpected 2>/dev/null",
            ]
        )
        peak = int(run([*docker, "exec", identifier, "cat", "/sys/fs/cgroup/memory.peak"]))
        current = int(run([*docker, "exec", identifier, "cat", "/sys/fs/cgroup/memory.current"]))
        size = json.loads(run([*docker, "image", "inspect", info["Image"]]))[0]["Size"]
        measured[name] = {
            "current_bytes": current,
            "peak_bytes": peak,
            "limit_bytes": host["Memory"],
            "image_bytes": size,
        }
    return measured


def main():
    validate_packaging()
    context_name = local_context()
    private_directory(CACHE)
    directory = Path(tempfile.mkdtemp(prefix="run-", dir=CACHE))
    private_directory(directory)
    context = certificate(directory)
    (directory / "compose.env").write_text("", encoding="utf-8")
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("COMPOSE_", "TRADING_"))
    }
    environment.update(
        TRADING_REHEARSAL_CERT=str(directory / "certificate.pem"),
        TRADING_REHEARSAL_KEY=str(directory / "key.pem"),
    )
    docker = ["docker", "--context", context_name]
    project = f"trading-package-{secrets.token_hex(8)}"
    (directory / "project.json").write_text(json.dumps({"project": project}), encoding="utf-8")
    compose = [
        *docker,
        "compose",
        "--project-name",
        project,
        "--project-directory",
        str(ROOT / "infra/application"),
        "--env-file",
        str(directory / "compose.env"),
        "-f",
        str(ROOT / "infra/application/compose.yaml"),
    ]
    # Environment is supplied to compose only; no application secrets are accepted.
    original_command = command

    def composed(args, **kwargs):
        return original_command(
            args, environment=environment if "compose" in args else None, **kwargs
        )

    # Helpers receive closures rather than inheriting ambient Compose overrides.
    try:
        print("Building locked local package...", flush=True)
        composed([*compose, "build", "--pull"], timeout=900)
        print("Checking HTTPS and container boundaries...", flush=True)
        composed([*compose, "up", "--detach", "--no-build"], timeout=300)
        assets = probe(context)
        idle = inspect_runtime(docker, compose, composed)
        started = time.monotonic()
        paths = ["/", "/api/v1/health/live", *assets] * 20
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda path: request(context, path)[0], paths))
        require(all(status == 200 for status in results), "Bounded workload failed.")
        report = {
            "measured_at": datetime.now(UTC).isoformat(),
            "scope": "locked shell and liveness; no authentication or financial workload",
            "requests": len(paths),
            "concurrency": 4,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "idle": idle,
            "after_workload": inspect_runtime(docker, compose, composed),
        }
        (CACHE / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    finally:
        composed([*compose, "down", "--timeout", "10"])
        directory.resolve().relative_to(CACHE.resolve())
        require(not directory.is_symlink(), "Refusing linked credential directory cleanup.")
        for filename in ("key.pem", "certificate.pem"):
            (directory / filename).chmod(0o600)
        shutil.rmtree(directory)
    print("PASS: local package rehearsal completed.")


if __name__ == "__main__":
    try:
        main()
    except (CheckFailure, DatabaseFailure, OSError, ValueError, KeyError) as error:
        message = (
            str(error)
            if isinstance(error, (CheckFailure, DatabaseFailure))
            else "Invalid local rehearsal configuration."
        )
        print(f"FAILED: {message}", file=sys.stderr)
        sys.exit(1)
