"""Check the current workflow's security contract before extending it."""

import re
import sys
import tomllib
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.tooling import ROOT, CheckFailure  # noqa: E402

PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-node": "949feb2413d6458794dcd2491c4babbbce0c15c1",
    "astral-sh/setup-uv": "07a047e608db84b3d8c06cd9a7c7dcc9c355c18e",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def validate_workflow(document: dict) -> None:
    require(
        set(document) == {"name", "on", "permissions", "concurrency", "jobs"},
        "Unexpected workflow controls; review defaults and environment changes.",
    )
    require(
        set(document["on"]) == {"push", "pull_request", "workflow_dispatch"},
        "Unsafe/missing workflow trigger.",
    )
    require(
        document["on"]["push"] == {"branches": ["dev", "main"]},
        "Push checks must cover both branches without path filters.",
    )
    require(
        document["on"]["pull_request"] == {"branches": ["main"]},
        "PR checks must not be filtered by paths or activity types.",
    )
    require(document["permissions"] == {"contents": "read"}, "Workflow token must be read-only.")
    require(
        set(document["jobs"]) == {"backend", "frontend", "repository", "database", "operations"},
        "Every verification job must be present.",
    )
    for name, job in document["jobs"].items():
        require(
            set(job) == {"name", "runs-on", "timeout-minutes", "steps"},
            "Unexpected job controls; review their security effect.",
        )
        require(
            job["runs-on"] == "ubuntu-24.04" and job["timeout-minutes"] == "20",
            "Use bounded disposable hosted jobs.",
        )
        expected_runs = [f"python scripts/checks.py {name}"]
        if name == "frontend":
            expected_runs.insert(
                0, "npm install --global --ignore-scripts --no-audit --no-fund npm@12.0.2"
            )
        require(
            [step["run"] for step in job["steps"] if "run" in step] == expected_runs,
            "Check commands cannot be skipped or replaced.",
        )
        actions = []
        for step in job["steps"]:
            require(
                set(step) <= {"name", "uses", "with", "run"},
                "Conditional or fail-open steps are not allowed.",
            )
            if "uses" not in step:
                continue
            action, _, pin = step["uses"].partition("@")
            require(
                action in PINS and pin == PINS[action], "Action must match its reviewed commit pin."
            )
            actions.append(action)
            options = step.get("with", {})
            if action == "actions/checkout":
                expected = {"persist-credentials": "false"}
                if name == "repository":
                    expected["fetch-depth"] = "0"
                require(
                    options == expected,
                    "Checkout must not persist credentials; secret scan needs full history.",
                )
            elif action == "astral-sh/setup-uv":
                require(
                    options
                    == {"version": "0.13.5", "python-version": "3.14.9", "enable-cache": "false"},
                    "Use pinned Python/uv without shared caches.",
                )
            else:
                require(
                    options
                    == {
                        "node-version-file": "frontend/.node-version",
                        "package-manager-cache": "false",
                    },
                    "Use pinned Node without shared caches.",
                )
        expected_actions = [
            "actions/checkout",
            "actions/setup-node" if name == "frontend" else "astral-sh/setup-uv",
        ]
        require(actions == expected_actions, "Missing or unexpected workflow action.")
    require(
        not any(
            value in str(document)
            for value in ("secrets.", "write-all", "pull_request_target", "self-hosted")
        ),
        "Privileged context is outside this workflow.",
    )


def validate_repository(root: Path = ROOT) -> None:
    workflows = list((root / ".github/workflows").glob("*.y*ml"))
    require(
        workflows == [root / ".github/workflows/verification.yml"],
        "Review additional workflows explicitly.",
    )
    # BaseLoader preserves YAML's `on` key and leaves scalar comparisons explicit.
    document = yaml.load(workflows[0].read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    validate_workflow(document)
    validate_postgres(root)
    validate_packaging(root)
    config = tomllib.loads((root / ".gitleaks.toml").read_text(encoding="utf-8"))
    require(
        config == {"title": "Repository secret detection", "extend": {"useDefault": True}},
        "Secret rules or exclusions changed; review the detector policy.",
    )
    require(
        not (root / ".gitleaksignore").exists(), "Secret baseline suppressions are not configured."
    )


def validate_postgres(root: Path = ROOT) -> None:
    def read(name):
        return yaml.safe_load((root / f"infra/postgres/{name}.yaml").read_text(encoding="utf-8"))

    base = read("compose")
    require(set(base) == {"services", "networks", "secrets"}, "Unexpected database composition.")
    require(set(base["services"]) == {"postgres"}, "Only local PostgreSQL belongs in this stack.")
    service = base["services"]["postgres"]
    require(
        set(service)
        == {
            "image",
            "environment",
            "secrets",
            "command",
            "healthcheck",
            "restart",
            "mem_limit",
            "cpus",
            "pids_limit",
            "shm_size",
            "security_opt",
            "logging",
        },
        "Review added container privileges/mounts.",
    )
    require(
        service["image"] == "postgres:17.11-bookworm@sha256:"
        "858bb5e98eed02eb8cafbcdc007f9a65d1b613972028944a8ec2133ccaf80d27",
        "Use the reviewed PostgreSQL image digest.",
    )
    require(
        service["environment"]
        == {
            "POSTGRES_USER": "trading_bootstrap",
            "POSTGRES_DB": "${TRADING_DB_NAME:?Use scripts/database.py}",
            "POSTGRES_PASSWORD_FILE": "/run/secrets/bootstrap",
            "POSTGRES_INITDB_ARGS": (
                "--auth-host=scram-sha-256 --auth-local=scram-sha-256 --data-checksums"
            ),
        },
        "Database initialization must use file credentials, SCRAM and checksums.",
    )
    require(
        service["secrets"] == ["bootstrap"]
        and base["secrets"]
        == {"bootstrap": {"file": "${TRADING_DB_SECRET_FILE:?Use scripts/database.py}"}},
        "Only the bootstrap password file is mounted into PostgreSQL.",
    )
    require(
        service["security_opt"] == ["no-new-privileges:true"], "Keep privilege escalation disabled."
    )
    require(
        base["networks"]
        == {
            "default": {
                "driver": "bridge",
                "driver_opts": {
                    "com.docker.network.bridge.host_binding_ipv4": "127.0.0.1",
                    "com.docker.network.bridge.enable_icc": "false",
                },
            }
        },
        "Keep a dedicated bridge with loopback publication and peer isolation.",
    )
    require(
        read("development")
        == {
            "services": {
                "postgres": {
                    "ports": ["127.0.0.1:55432:5432"],
                    "volumes": ["development-data:/var/lib/postgresql/data"],
                }
            },
            "volumes": {"development-data": None},
        },
        "Development must keep its private port and dedicated persistent volume.",
    )
    require(
        read("test")
        == {
            "services": {
                "postgres": {
                    "ports": ["127.0.0.1::5432"],
                    "tmpfs": ["/var/lib/postgresql/data:rw,noexec,nosuid,size=256m"],
                }
            }
        },
        "Tests must use an ephemeral loopback port and disposable memory storage.",
    )


def validate_package_ports(configured: dict, effective: dict) -> None:
    expected = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
    require(configured == expected, "Public gateway port.")
    # Linux engines may retain image EXPOSE entries with null/empty bindings.
    # They are not published. The actual HTTPS mapping must still be present.
    published = {port: bindings for port, bindings in effective.items() if bindings}
    require(published == expected, "Gateway mapping did not take effect or exposes extra ports.")


def validate_packaging(root: Path = ROOT) -> None:
    document = yaml.safe_load((root / "infra/application/compose.yaml").read_text(encoding="utf-8"))
    require(set(document) == {"services", "networks", "secrets"}, "Unexpected package resources.")
    require(set(document["services"]) == {"api", "gateway"}, "Unexpected package service.")
    shared = {
        "image",
        "user",
        "read_only",
        "cap_drop",
        "security_opt",
        "tmpfs",
        "mem_limit",
        "memswap_limit",
        "cpus",
        "pids_limit",
        "ulimits",
        "restart",
        "logging",
    }
    for name, memory, cpus, pids in (("api", "256m", 0.75, 64), ("gateway", "64m", 0.25, 32)):
        service = document["services"][name]
        extra = (
            {"build", "network_mode", "depends_on"}
            if name == "api"
            else {"entrypoint", "ports", "volumes", "secrets"}
        )
        require(set(service) == shared | extra, "Unexpected package override or credential source.")
        require(
            service["user"] == "10001:10001" and service["read_only"] is True,
            "Package must be non-root/read-only.",
        )
        require(
            service["cap_drop"] == ["ALL"]
            and service["security_opt"] == ["no-new-privileges:true"],
            "Package capabilities changed.",
        )
        require(
            service["mem_limit"] == service["memswap_limit"] == memory
            and service["cpus"] == cpus
            and service["pids_limit"] == pids,
            "Package budget changed.",
        )
        require(
            service["ulimits"] == {"core": 0} and service["restart"] == "no",
            "Dump/restart policy changed.",
        )
        require(
            service["tmpfs"]
            == ["/tmp:rw,noexec,nosuid,nodev,size=16m,uid=10001,gid=10001,mode=0700"],
            "Temporary storage policy changed.",
        )
        require(
            service["logging"]
            == {"driver": "local", "options": {"max-size": "1m", "max-file": "2"}},
            "Unbounded logs.",
        )
    api, gateway = document["services"]["api"], document["services"]["gateway"]
    require(
        api["network_mode"] == "service:gateway" and api["depends_on"] == ["gateway"],
        "API namespace changed.",
    )
    require(
        api["image"] == "trading-app:local-rehearsal"
        and api["build"] == {"context": "../..", "dockerfile": "infra/application/Dockerfile"},
        "Unexpected build context.",
    )
    require(
        bool(re.fullmatch(r"nginx:[a-z0-9.-]+@sha256:[a-f0-9]{64}", gateway["image"])),
        "Proxy image must be digest pinned.",
    )
    require(gateway["ports"] == ["127.0.0.1:8443:8443"], "Gateway must stay on loopback.")
    require(
        gateway["entrypoint"] == ["nginx", "-g", "daemon off;"]
        and gateway["volumes"]
        == [
            {
                "type": "bind",
                "source": "./nginx.conf",
                "target": "/etc/nginx/nginx.conf",
                "read_only": True,
            }
        ],
        "Unexpected proxy entrypoint/mount.",
    )
    require(
        gateway["secrets"] == ["tls_certificate", "tls_key"]
        and document["secrets"]
        == {
            "tls_certificate": {"file": "${TRADING_REHEARSAL_CERT:?Use scripts/operations.py}"},
            "tls_key": {"file": "${TRADING_REHEARSAL_KEY:?Use scripts/operations.py}"},
        },
        "Unexpected package secrets.",
    )
    require(
        document["networks"]
        == {
            "default": {
                "driver_opts": {
                    "com.docker.network.bridge.host_binding_ipv4": "127.0.0.1",
                    "com.docker.network.bridge.enable_icc": "false",
                },
            }
        },
        "Rehearsal requires loopback publication and peer isolation.",
    )
    dockerfile = (root / "infra/application/Dockerfile").read_text(encoding="utf-8")
    sources = re.findall(r"^FROM (\S+)", dockerfile, re.M)
    require(
        len(sources) == 4
        and all(re.fullmatch(r"[a-z0-9./:-]+@sha256:[a-f0-9]{64}", source) for source in sources),
        "All build images must be pinned.",
    )
    require(
        dockerfile.rstrip().endswith(
            'USER 10001:10001\nENTRYPOINT ["python", "-m", "trading_api.packaged"]'
        ),
        "Runtime identity/entrypoint changed.",
    )
    allowed = {
        "backend/",
        "backend/pyproject.toml",
        "backend/uv.lock",
        "backend/trading_api/",
        "backend/trading_api/*.py",
        "backend/trading_auth/",
        "backend/trading_auth/*.py",
        "backend/trading_db/",
        "backend/trading_db/*.py",
        "frontend/",
        "frontend/package.json",
        "frontend/package-lock.json",
        "frontend/workspace.config.ts",
        "frontend/workspace-boundary.ts",
        "frontend/src/",
        "frontend/src/design.css",
        "frontend/workspace/",
        "frontend/workspace/index.html",
        "frontend/workspace/src/",
        "frontend/workspace/src/*.ts",
        "frontend/workspace/src/*.tsx",
        "frontend/workspace/src/*.css",
        "infra/",
        "infra/application/",
        "infra/application/Dockerfile",
    }
    ignore = (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    require(
        ignore[0] == "**" and set(ignore[1:]) == {"!" + path for path in allowed},
        "Build context must exclude credentials, demo, tests and local files.",
    )


if __name__ == "__main__":
    validate_repository()
    print("Workflow security policy passed.")
