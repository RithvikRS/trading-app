"""Check the current workflow's security contract before extending it."""

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
        set(document["jobs"]) == {"backend", "frontend", "repository", "database"},
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


if __name__ == "__main__":
    validate_repository()
    print("Workflow security policy passed.")
