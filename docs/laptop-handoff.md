# Laptop handoff

Snapshot: 10 November 2026. Implementation is paused. This document and the private transfer package preserve the work needed to continue on another computer.

## Start here

Take **`trading-app-laptop-handoff-20261110.zip` and its `.sha256` companion file**. The package contains an offline Git bundle, unfinished source snapshots, verification evidence, designs, a file inventory and a read-only integrity checker. A normal Git clone contains the committed application and this guide, but **does not contain the unfinished work**.

The last implementation/planning merge before this handoff was [PR #93](https://github.com/RithvikRS/trading-app/pull/93), commit `506548d240d309d48e2f3d8e7828a2bb564a0785`. The handoff's documentation commit is later; `TRANSFER.json` in the package records its exact exported revision. Feature manifests keep their original bases intentionally.

The current application still uses PostgreSQL and Supabase. The new direction is Oracle Autonomous Database, native Authelia OIDC and an independent Ampere/Caddy/Swarm release. The Oracle/OIDC drafts are unmerged and do not change the running application. Read the [architecture decision](oracle-authelia-decisions.md), [migration sequence](oracle-authelia-migration.md) and [product plan](plan.md) alongside this dated checkpoint. Earlier wording about absent Oracle tooling or unfinished shared infrastructure predates the latest saved work.

## Move to the laptop

1. Copy the ZIP and checksum file to a private local folder. Check the ZIP with `Get-FileHash -Algorithm SHA256` and compare it with the companion checksum before extracting into a new directory. The checksum detects transfer corruption; keep both files from the trusted original copy.
2. In the extracted directory, run `python verify-transfer.py`. It only verifies the file inventory; it does not install tools, copy files into a repository, or run saved scripts.
3. Clone the repository, using either the online or offline route below. Use a full clone so history-based checks and saved feature bases remain available.
4. Copy the **contents** of the extracted `repo-cache` directory into the new clone's `.cache` directory. This restores private checkpoints, not active application source. For a fresh clone, from the extracted package directory:

   ```powershell
   New-Item -ItemType Directory -Path ../trading-app/.cache -Force
   Get-ChildItem -LiteralPath ./repo-cache -Force |
     Copy-Item -Destination ../trading-app/.cache -Recurse
   ```

   Adjust the destination to the actual new clone. Use an empty destination for this first restore; do not overwrite another machine's active checkpoints.
5. Open `docs/laptop-handoff.md` in the clone. Read `.cache/oracle-conversion-pause-20261110/checkpoint.json` and the feature manifests before restoring any draft into source files. Absolute old-machine paths are historical metadata and must be mapped to the new clone deliberately.
6. Recreate local tooling from the lockfiles, authenticate Git locally on the laptop, then resume the next item below. Keep the original ZIP as an unchanged backup.

Online clone:

```powershell
git clone https://github.com/RithvikRS/trading-app.git ../trading-app
git -C ../trading-app switch dev
```

Offline clone, from the extracted package directory:

```powershell
git clone -b main ./trading-app.bundle ../trading-app
git -C ../trading-app switch --track origin/dev
git -C ../trading-app remote set-url origin https://github.com/RithvikRS/trading-app.git
```

The bundle contains committed `main` and `dev` history. It does not contain pull-request discussion, credentials or installed dependencies. An offline clone permits source work; first-time dependency/image installation, vulnerability checks, provider verification and pushing still require network access. Fetch before the next integration to inspect any newer remote work.

Do not copy a worktree's `.git` file as a repository: it points into the original computer's main checkout. Restore drafts into fresh isolated checkouts from their recorded bases, review the differences against current `main`, and integrate one feature at a time. Shared application/frontend hooks overlap across the saved increments; applying every snapshot together would overwrite work.

## Saved work that must travel

These paths are inside `repo-cache` in the package and become `.cache/...` after restoration. Earlier phases are retained as evidence; use the current manifest listed here as each feature's starting point.

| Increment | Current snapshot and restore layout | Status and work left |
| --- | --- | --- |
| **OA2.1 Oracle verifier** | `oracle-conversion-pause-20261110/oracle/manifest.json`; each file lives at its manifest-relative path | 20 source/config/doc files. 78 focused tests, Ruff and strict mypy passed before the final IPv4/IPv6 guard edit; Ruff passed afterward. Three smoke attempts failed before Oracle container creation. Diagnose the actual network profile, rerun affected checks, pass the real smoke and obtain final source review. |
| **OA3.1 OIDC contracts** | `oracle-conversion-pause-20261110/oidc/.cache/oidc-contracts/handoff.json`; six source paths relative to the enclosing `oidc` directory | 128 pure tests and independent source review passed. Integrate separately with central typing/docs updates and full checks. No routes, durable callback consumption or session authority. |
| **OA3.2 offline ID-token verifier** | `oracle-conversion-pause-20261110/oidc/.cache/oidc-verification/handoff.json`; three additional source paths relative to `oidc` | 148 additional cases; 276 combined tests, Ruff and strict mypy passed. Independent review and integration remain. Authlib `1.9.5` and joserfc `1.8.0` exist only in the old scratch environment; project pins are still pending. |
| **8B.3 bank account archival** | `bank-account-archive-checkpoint/paused-20261029/manifest.json`; `source/<path>`, `prerequisites/<path>`, `canonical-preimages/<path>`, `evidence/<path>` | 15 feature files. Earlier 110 pure/29 database cases passed; latest HTTP/database batch passed 18 after a preserved one-line fixture correction. Review that correction, adapt dependencies, finish frontend/build/browser and final checks. |
| **5F.3.1 NAV growth mappings** | `nav-growth-mapping-checkpoint/source-integrated/manifest.json`; source/evidence at manifest-relative paths | 13 feature files; 105 Python/38 database cases and static checks passed on the recorded base. Frontend runtime/build/browser and final integration remain. No schema change. |
| **9B.8.3 HDFC billing-account setup** | `credit-billing-setup-checkpoint/source-phase-3/manifest.json`; use each entry's `backup` field | 24 feature files; unit/static checks and source review retained. Database, frontend/build/browser and final checks remain. Its unmerged PostgreSQL `0026` / recovery-format-22 candidate needs reconciliation with the Oracle baseline. |
| **5F.3.2 manual NAV preview** | `nav-growth-mapping-checkpoint/nav-manual-preview-proposal-v3-20261029.json` and corresponding `nav-manual-preview-review-v3-20261029.json` | Reviewed design only. Preserve bounded upload, cancellation/worker custody and privacy requirements; no preview implementation exists. |

The six implementation drafts contain **81 source/config/doc file entries** across snapshots, including overlapping paths. This is not a count of remaining product steps. The package preserves preceding checkpoint phases, failed attempts, source preimages and the latest NAV design/review. Old bank-archive and credit-setup worktree directories are not authoritative; their saved backups are.

The Oracle diagnostic run `453f59b087284dc357a147447f2c4f9e` has outcome `pending` because it inspected only a network. All four Oracle run manifests say `cleaned`; no verifier or run-owned container/network was left running at the pause. **No real Oracle smoke has passed.** Keep old run manifests as evidence inside the snapshot; do not install them as active lifecycle state on the laptop or run old cleanup commands against new resources.

## Resume order

1. Verify transfer and feature hashes. For Oracle, compare the preserved `network-profile.json` against the `EnableIPv4` / `EnableIPv6` guard in `trading_oracle/local.py`. Resolve the actual mismatch while retaining literal-loopback publication, custody validation, resource limits and guarded cleanup. Check the draft first-failure explanation against evidence before publishing it.
2. Finish OA2.1's focused checks, actual disposable Oracle smoke, independent review and full integrated verification. Start from its 20-file snapshot, review any required fixes/additions, reconcile central docs with this handoff, and retain failed attempts.
3. Integrate OA3.1, then independently reviewed OA3.2, through separate PRs. Preserve the six frozen contract files while reviewing the verifier. Pure signed-token tests do not prove provider behavior or durable replay prevention.
4. Implement **OA2.2**, a separate synthetic owner/identity/preference baseline: restricted bootstrap/migration/runtime/auth responsibilities, trusted owner context and database-enforced isolation, bounded pool cleanup and an interrupted-DDL journal. Oracle DDL commits implicitly; rollback is not a schema-recovery strategy. A runtime caller selecting an owner is not itself proof of authentication.
5. Complete the rest of **OA2** and **OA3**, including durable single-use attempts, provider acquisition, explicit enrollment, opaque app sessions, MFA freshness, revocation/offboarding, recovery and a pinned non-production Authelia rehearsal.
6. **OA4**: one protected preference/account flow through Oracle and the frontend, with two-user isolation and stale-context/revision behavior.
7. **OA5**: port financial domains and encrypted recovery in small increments. Retain applied PostgreSQL history and historical recovery decoders; preserve exact native values, source spelling, ownership and concurrency guarantees. Re-enter the three saved financial features when their actual dependencies are ready.
8. **OA6/OA7**, coordinated with Stage **11**: ARM/Swarm/Caddy synthetic staging, monitored recovery, real data/identity inventory and deliberate production cutover. Local tests do not authorize live provider acquisition or establish hosted readiness.

The owner reports shared infrastructure complete. Portfolio repository evidence was reviewed at `61d10b7ff10a3a63e0a73fdd67c4b10999d34d67`; repeating the earlier shared-readiness questions is unnecessary. Trading-specific Oracle TLS/privileges, Authelia assurance/offboarding, deployment, independent alerts and full restore evidence still require actual acceptance. Record remaining service/hostname/retention/provider decisions for their relevant stage.

## Completed baseline and remaining product roadmap

Completed features remain the PostgreSQL/Supabase behavioral baseline. Synthetic prototypes are separate from connected production capabilities.

| Area | Completed baseline | Remaining work |
| --- | --- | --- |
| Stages **1-4** | Planning; Indigo & Apricot light/dark prototypes; secure Python/database/session shell; exact financial persistence and protected reads through **4G.3b** | Port required behavior through OA2-OA5; hosted acceptance remains separate. |
| [Stage 5](investment-flow-plan.md) | **5A**, **5B.1**, **5E.0**, **5E.1**, **5F.1**, **5F.2** | Remaining isolated intake, verified CAS format for demonstrated API gaps, source-specific staging/completion, upload/activity UI, NAV mapping/preview/persistence/selection/valuation, **5G** acceptance/recovery. |
| [Stage 6](indmoney-integration-plan.md) | Discovery/custom-client research, synthetic authorization/custody, bounded reader engine, saved snapshots/coverage and public history/capability assessment | Actual account/history/token-renewal acceptance, verified live adapter, authenticated history contract and **6F** recovery. Check the API before choosing statement workarounds. |
| [Stage 7](ubs-integration-plan.md) | **7A**, **7B.1-7B.3**, **7B.4.1-7B.4.2** saved-evidence views | **7C** account-specific API/OFX/export contract; **7D.1** acquisition/staging; **7D.2** reviewed ESPP lots/activity; **7E** source-specific share/cash reconciliation. |
| Stage **8** | **8A.1-8A.4**, **8B.1-8B.2**, **8C.1** saved banking/setup/source/cash views | Saved **8B.3**; first-source registration; verified HDFC/SBI acquisition/import; cash coverage/selection; durable transfers, categories, recurring expenses and budgets. Further IDs are not fully assigned. |
| [Stage 9](credit-cards-plan.md) | **9A**, **9B.1-9B.5**, **9B.6.1**, **9B.7.1-9B.7.2**, **9B.8.1-9B.8.2** | Saved **9B.8.3**; card membership, statement allocation and selection/completion; **9C.1** verified HDFC import/preview; **9C.2** reviewed completion/statements; **9D** payment matching and spending/budgets. |
| Stages **10-11** | Plans and local package/recovery foundations | Durable schedules/retries/renewal, valuation history/returns, hosted release/monitoring/recovery/security acceptance aligned with OA6/OA7. |

The previous estimate of about 48 remaining financial substeps predates the conversion and is not a current total. Six implementation increments and one design are saved; OA2-OA7 and remaining product work still need further decomposition. Multi-user onboarding and trade execution remain future extensions.

## Tooling, credentials and additional folders

Use [development](development.md) and [verification](verification.md) for commands. Recorded pins are Python **3.14.9**, uv **0.13.5**, Node **22.23.2** and npm **12.0.2**, plus a local Docker Engine with Compose. Rebuild `backend/.venv` using `uv sync --locked` and frontend dependencies using `npm ci --ignore-scripts --no-audit --no-fund`; keep lifecycle-script restrictions. The existing verifier tool assets support Windows/Linux x86-64. An ARM/macOS laptop requires an explicit tooling compatibility check; an ARM Oracle image manifest does not prove the complete local test setup works there.

OA2.1 pins `oracledb==26.1.0` and the official image:

```text
container-registry.oracle.com/database/free:23.26.3.0@sha256:f988b0c04c4c386cd306a2a914c0d7a9702d83acc31b064a28ad8eb6278a8fba
```

The image is already cached on the original desktop, but is intentionally absent from the transfer package. Its compressed download was about 3.7 GB; the draft gives its container 3 GiB RAM with no additional swap allowance. Plan space for the extracted image and disposable databases. Download and install dependencies while online before travelling if offline development is needed. No laptop installation or ARM execution has been verified by this handoff.

| Item | Copy or recreate? |
| --- | --- |
| Repository history and ignored feature checkpoints | Included in the ZIP. This is the essential additional material beyond a Git clone. |
| Portfolio infrastructure repository | Clone separately when deployment work needs it: [Portfolio-website](https://github.com/RithvikRS/Portfolio-website). Recorded reference `61d10b7...`; no private infrastructure material is needed for local conversion. |
| `.venv`, `node_modules`, build outputs, uv/npm caches, browser installs and Docker images | Recreate from pinned dependencies. Existing machine paths, junctions and binaries are not portable setup. |
| Git credentials, SSH keys and Windows Credential Manager | Authenticate locally on the laptop. Do not copy credential stores or embed tokens in remotes. The optional private `github-local.ps1` helper is included without credentials and uses the laptop's local Git credential helper. |
| `.env*`, private key directories, wallets, provider tokens, database credentials, statements and real financial data | Excluded. None is needed to resume synthetic conversion. Transfer only separately if later required, using the project's encrypted backup/recovery procedure and private key custody. |
| Existing development database/volumes | Not needed for the saved synthetic work; create fresh disposable environments. If real local-only data exists outside this handoff's scope, inventory and back it up separately rather than copying a live Docker data directory. |
| Chat history or old worktree folders | Not required. The guide, manifests and source/evidence snapshots carry the resume state. |

The package may contain private development paths, synthetic fixtures and detailed test evidence; keep it private. Secret scanning reduces accidental credential exposure but is not a claim that the archive is suitable for publication.

## Delivery workflow

Continue small conventional commits on persistent `dev`, one coherent PR into `main` per increment, with sequential integration and merge after passing local verification and review. Independent work can proceed in isolated checkouts; coordinate shared hooks and keep one heavy database/build/browser verification lane at a time.

GitHub Actions stays manual. At the committed handoff baseline, `python scripts/checks.py all` has five groups. The unmerged OA2.1 draft adds the mandatory sixth **Oracle** group; after integration, all six must pass for code/configuration changes. Do not remove or skip the Oracle group to get a successful result. Documentation-only changes may use repository checks under the [PR standard](pull-requests.md).

Retain initial failures, actual tested source hashes and cleanup evidence. Refresh local paths and immutable base checks in old private runners before reuse; never weaken their assertions or treat old environment results as acceptance on the laptop. Keep real statements, identifying data and credentials out of commits and PRs. The UI direction remains Indigo & Apricot in both themes, with clear chart contrast and masking.

## Suggested resume message

> Read `docs/laptop-handoff.md` and `.cache/oracle-conversion-pause-20261110/checkpoint.json`. Verify the restored manifests and repository state. Resume OA2.1 at the preserved network-profile mismatch, then complete Oracle/OIDC conversion and the remaining roadmap. Use isolated parallel work where useful and sequential conventional dev-to-main PRs after required local checks. Keep GitHub Actions manual, preserve failed evidence and record remaining hosted/provider questions for later. The saved financial drafts are inputs to adapt, not completed features.
