# OA2.1: isolated local Oracle verification

This increment adds a disposable Oracle Database Free smoke runner. PostgreSQL remains the application's active persistence implementation. No application route, session, migration, owner policy or financial record is moved to Oracle here.

## Boundary

Run from the repository root after installing the locked backend dependencies:

```powershell
python scripts/checks.py oracle
```

The underlying command is `python -m trading_oracle check` from `backend`. After validating the local Docker context, it obtains the exact digest-pinned official image if missing, with a bounded 600-second download. It does not perform a registry login or fall back to another image; container creation itself forbids automatic pulls. The image is Oracle Database Free `23.26.3.0`, pinned to multi-platform digest `sha256:f988b0c04c4c386cd306a2a914c0d7a9702d83acc31b064a28ad8eb6278a8fba`. Registry metadata includes native Linux AMD64 and ARM64 manifests. Local execution evidence must identify the tested architecture; manifest availability is not an ARM runtime result.

The runner requires Docker Engine 28 or newer, a local Linux daemon, and no Docker endpoint or Oracle connection-environment overrides. Each run has an unpredictable identifier, an exclusive process lock, a private ownership manifest and generated credentials below the ignored `.cache/oracle/runs` directory. Windows custody requires a current-user or SYSTEM-owned directory, atomically replaces its protected DACL with exactly those two FullControl grants, and verifies the result. Unrelated explicit grants are removed only inside the Oracle cache; administrative control of the local host remains trusted. POSIX directories are mode 0700. The bootstrap file alone is mode 0444 inside that private parent so the container's different `oracle` user can read the explicitly mounted file. The application probe credential stays mode 0600. These are synthetic disposable credentials, never provider or production secrets.

One dedicated bridge publishes only an inspected random IPv4 loopback port. Its default host binding is 127.0.0.1 and inter-container communication is disabled. This bridge does not deny outbound network traffic; no external database or provider connection is part of the runner.

The container runs as the image's non-root `oracle` user, with all Linux capabilities dropped, no new privileges, 3 GiB memory with no additional swap allowance, 2 CPUs, 1 GiB shared memory and 512 PIDs. It has no database volume, application mount, host network or Docker socket. Only the generated bootstrap password file is mounted read-only at `/run/secrets/oracle_pwd`. Passwords are not passed through Docker environment variables, command arguments or health checks. Container logging is disabled, and raw driver/tool output is not printed or retained by the runner.

The pinned image's password-file script is checked separately from current upstream documentation. Runtime safety checks verify the image, container name/labels, network/options, resources, mounts and listener. Cleanup refuses replaced resource identities or unrelated network members and never deletes mounted data or Docker volumes.

## Smoke checks

Bootstrap waits for the exact `FREEPDB1` PDB to report `READ WRITE` and unrestricted access; a successful query against `dual` does not establish that state. The fixed service then receives a synthetic `TRADING_SMOKE` user with CREATE SESSION, CREATE TABLE and a small USERS quota. Controlled bootstrap SQL arrives over standard input. A run marker binds subsequent work to this disposable database. This identity is solely a test schema; it is not the future application's runtime identity or ownership model.

A fresh Python process with `-I -S` skips sitecustomize and .pth startup code, adds only its verified locked-virtualenv package directory, and enables python-oracledb Thin mode with a private empty configuration directory. It uses explicit fixed host, service and user arguments, an inspected port, no DSN/alias/plugin inputs, UTC, zero connection retries and bounded connection/call/process deadlines. The probe verifies:

- Wrong-password rejection by the expected authentication error.
- The expected database version, PDB, user and run marker.
- Exact Decimal bind/fetch for 30-digit and small fractional values, preserving source text independently.
- Native date round-trip and UTC session configuration.
- Committed DML visible through a separate physical connection, with rolled-back DML absent.

These checks do not establish Oracle VPD, multi-owner isolation, hosted TLS, Autonomous privileges, durable migrations, whole-domain precision or production recovery. Those remain later migration increments.

## Interruption and cleanup

The ownership manifest exists before secret creation and records immutable image/container/network identifiers as they become available. Partial initialization remains recoverable. The process lock serializes checks and cleanup and is released by the operating system on process exit. A failed cleanup retains the manifest and any credentials not yet safely removed. Recover only the recorded run identifier:

```powershell
cd backend
python -m trading_oracle cleanup <32-character-run-id>
```

Cleanup revalidates the local daemon and immutable resource custody independently of the runtime resource profile, so a rejected runtime configuration can still be stopped safely. It removes only the run's container and network, verifies their absence, then removes its credential files and empty configuration directory. It never prunes Docker, drops an existing database/schema, recursively deletes a supplied path or touches the PostgreSQL development volume. Success retains a small manifest with the outcome and cleaned status. Paths containing symlinks, Windows junctions/reparse points or hardlinked credential files are refused.

## Verification evidence

On 15 November 2026, 89 focused tests passed with Ruff, formatting and strict typing. Cases cover closed descriptors, forbidden environment overrides, malformed ownership manifests, path/resource substitutions, exact IPv4/IPv6 fields, bounded PDB readiness, actual cleanup after a rejected runtime profile, removal of unrelated Windows grants and permission failure before secret creation.

The real disposable smoke passed on a Windows AMD64 host with Docker Engine 29.6.1 running Linux x86-64, Python 3.14.9 and python-oracledb 26.1.0 Thin mode. The final rerun after the DACL change passed all probe checks and removed its container, network, credential files and empty configuration directory; only the nonsecret manifest remained. Linux ARM64 execution, POSIX permission runtime acceptance, hosted service compatibility and the final integrated repository gate remain separate evidence.

Earlier failures are retained. The first attempt started its container and failed the published-listener binding guard on an internal bridge; attempts two and three failed before container creation at network-profile validation. A new network-only diagnostic established that IPv4/IPv6 flags are root fields, while the options map contains the requested bridge settings. Attempts four and five exposed a readiness query that admitted a still-mounted PDB; bootstrap now requires the documented writable, unrestricted state. The first exact-DACL regression also exposed incompatible inherited PowerShell module paths; direct .NET ACL calls with module autoloading disabled removed that dependency without relaxing the permission checks. All owned runtime resources were cleaned after these attempts.

References: [official Oracle images](https://github.com/oracle/docker-images/tree/main/OracleDatabase/SingleInstance), [Oracle Free registry and license](https://container-registry.oracle.com/ords/ocr/ba/database/free), [PDB open state](https://docs.oracle.com/en/database/oracle/oracle-database/26/refrn/V-PDBS.html), [python-oracledb installation](https://python-oracledb.readthedocs.io/en/stable/user_guide/installation.html), [migration roadmap](oracle-authelia-migration.md).
