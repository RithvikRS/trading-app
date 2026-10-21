# Security requirements

Security is the highest project priority. These requirements cover confidentiality, integrity, and availability of financial data. They are planned controls; completion must be demonstrated before the relevant feature is used with personal data.

The current Overview, Investments, and Banking prototype uses fictional records, loopback-only servers, bundled assets, restrictive browser headers, and display-only preference storage. Searches and screen controls stay in memory; routes use allowlisted screen names and opaque fixture IDs without financial values or account/folio details. Unknown or malformed detail routes show an unavailable screen. Masking hides amounts, units, quotes, lot purchases/fees, bank balances/movements, reconciliation differences, and activity values in the DOM and accessible attributes. Transaction inspection also suppresses raw narration/reference, since source text can contain amounts. Banking source records are immutable fixtures. Transfer decisions and undo history stay in memory, separate from original records; category editing remains planned. Matching checks known sample account ownership, posting state, equal native amounts/currency, source roles, and the three-day calendar window. Confirmation revalidates availability and exclusive pair membership. These client-side fixture checks are not authentication or production authorization. Pair previews, structured references, coverage values, and announcements follow shared privacy rules. See its [implemented boundaries and limitations](ui-prototype.md#security-boundary). Authentication, database policies, secret scanning, and production hosting protections remain future work; no real data belongs in the prototype.

## Assets and trust boundaries

Protect bank and investment records, statements, identifiers, session tokens, integration credentials, encryption keys, backups, and financial calculation history. A broker token may permit trading even when this app only displays holdings; record the provider's actual permissions.

Trust boundaries include the browser and API, public network and application host, host and Supabase, worker and financial providers, uploaded document and parser, administrator and runtime identities, and primary storage and backups. External statements, connector responses, descriptions, and imported links are untrusted input.

## Threat model

| Threat | Required response | Verification |
| --- | --- | --- |
| Account takeover or stolen session | MFA, protected sessions, rate limits, revocation, and tested recovery | Rejected invalid/expired sessions, renewal and logout tests, recovery exercise |
| Unauthorized record access | Server-side ownership checks and database policies with a restricted runtime role | Cross-account and future cross-user access tests, including pooled connections and jobs |
| Exposed database or credentials | Network restrictions, verified TLS, least privilege, external secret management, and redacted logs | Negative connection tests, role/grant inspection, secret scanning |
| Malicious statement or provider payload | Constrained isolated parsing, validation, safe rendering, and no arbitrary URL fetching | Malformed/oversized file, resource exhaustion, injection, and outbound-access tests |
| Duplicate, forged, or partial imports | Source attribution, idempotency, atomic commits, reconciliation, and reviewed corrections | Reupload, overlap, interrupted-import, and mismatch tests |
| Compromised dependency, build, or server | Locked dependencies, vulnerability review, constrained containers, patching, and restricted CI | Dependency/container review and deployed configuration inspection |
| Deleted data, ransomware, or provider loss | Independent encrypted backups, restricted deletion rights, and tested restoration | Restore into an isolated environment and reconcile records |
| Overpowered broker integration | Prefer provider-enforced read-only scopes and separate execution credentials | Document and verify token capabilities before enabling a connector |

## Authentication and sessions

Choose a maintained authentication solution during foundation planning. Require MFA for the owner and administrative cloud accounts, disable public registration for the personal version, and review enrollment and recovery as part of authentication. Do not build custom cryptography.

Use short-lived or bounded sessions with server-side revocation and secure, HttpOnly, appropriately SameSite cookies. Protect state-changing requests against CSRF and validate origins. Keep credentials and refresh tokens out of browser local storage, URLs, and frontend bundles. Use exact CORS allowlists, rate limits, generic authentication errors, and documented expiry behavior.

Restrict the personal deployment through a private network or identity-aware gateway as well as application authentication. The gateway is an additional boundary, not a replacement for API authorization. Its product and recovery method remain to be selected.

## Database access

- Permit hosted database access only from explicitly allowed application and administrative network addresses, covering the actual IPv4/IPv6 and pooler routes used.
- Enforce TLS and verify the server certificate and hostname. Connection failures must not trigger an unencrypted fallback.
- Disable unused Supabase REST/GraphQL Data API access and keep financial tables in an unexposed schema. Review grants on new tables, functions, and sequences; do not rely on project defaults.
- Give API and worker roles only necessary operations. They must not be schema owners, superusers, or roles that bypass row-level security. Separate migrations and backup privileges from runtime credentials.
- Enforce ownership in the API and row-level security where applicable. Define how trusted server-authenticated identity reaches database policies; an arbitrary client-supplied owner ID must never authorize access. Test identity cleanup across pooled transactions, failures, and background jobs.
- Treat administrative consoles, service credentials, and migration roles as privileged access. MFA, limited use, and auditability apply to them too.

Reference: [Supabase network restrictions](https://supabase.com/docs/guides/platform/network-restrictions), [TLS enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement), and [Data API security](https://supabase.com/docs/guides/api/securing-your-api).

## Secrets and encryption

Prefer official OAuth or scoped provider authorization. Login and consent should occur at the provider where supported. Bank passwords and broad mailbox access are not default import mechanisms. Document scopes, renewal, expiry, and revocation for every integration. A connector requiring credentials that also permit trading needs a separate documented decision before it is enabled.

Keep integration secrets server-side and encrypt persisted tokens with authenticated encryption from a maintained library. Manage keys outside the database and its backups, using a secret manager or KMS with narrowly scoped workload identity. OCI Vault is a candidate; the exact key custody and recovery design remains to be selected. Record key versions and test rotation and revocation.

Require protected storage for database data, statements, backups, and VM disks. Review swap encryption and crash-dump behavior because decrypted statements and secrets may appear in process memory. Protect decryption keys separately from the encrypted data. Encryption at rest does not prevent an attacker controlling the authorized application from reading data; least privilege, host isolation, and incident response remain necessary.

Never commit live credentials, private statements, PAN/account identifiers, dumps, or decrypted fixtures. Configure ignore rules and secret scanning before introducing any real data or secrets. Development and tests use separate credentials and synthetic or irreversibly sanitized data.

## Statement ingestion and data privacy

Validate type and content instead of trusting filename extensions. Restrict file size, page count, parser time, memory, and concurrency. Parse with a non-root isolated process, no provider credentials, and network access disabled unless a specific reviewed requirement exists. Reject unsupported formats rather than invoking unsafe conversion or macros. Review PDF, archive, and spreadsheet dependencies before accepting those formats.

Store uploads privately with opaque identifiers, authorized downloads, and no public URLs. Retain originals only for a defined reconciliation period or explicit user need. Remove temporary decrypted files after processing and on failure. PDF passwords must not enter logs or persistent storage by default.

Escape imported text in the interface, sanitize any permitted rich content, use a restrictive content security policy, and prevent spreadsheet formula injection in exports. Allowlist connector destinations to avoid server-side request forgery. Do not execute instructions, scripts, or links found in imported content.

Minimize logs and metrics: keep event type, result, timing, and pseudonymous identifiers; redact tokens, document contents, account numbers, and full provider payloads. Define retention for statements, financial records, audit events, and backups, including how deletion propagates and when retained backups expire. Do not send financial data to third-party analytics or external data-processing services without a separately reviewed purpose and explicit authorization.

## Delivery and operations

Pin and lock dependencies, review known vulnerabilities, scan for secrets before commits, and grant CI minimal permissions. Build using synthetic data and keep production secrets out of build output and logs. Use non-root containers, narrow filesystem permissions, resource limits, and minimal exposed ports. Restrict SSH administration and keep OS and dependencies patched.

Audit security-relevant events, import confirmations, permission changes, exports, corrections, and future orders. Use append-only application permissions for audit records and consider independent audit copies before multi-user or trading use. Do not claim that records held on a compromised host are inherently tamper-proof.

Backups, restore exercises, monitoring, and incident handling are specified in [operations](operations.md). Treat backup contents and recovery credentials as production-sensitive data.

## Release gates

The local UI prototype uses fictional data only. Before handling real data, verify authentication, ownership checks, secret handling, private storage, and safe ingestion. Before hosted use, additionally verify:

1. MFA, registration restrictions, session revocation, account recovery, and protected network entry work.
2. Database network restrictions and certificate verification reject unauthorized or invalid connections.
3. Runtime roles and policies prevent unauthorized access; migrations cannot accidentally expose tables.
4. Logs, builds, commits, and error responses contain no secrets or personal records.
5. Import atomicity, deduplication, and reconciliation prevent silent data corruption.
6. Encrypted backups and separately protected keys restore successfully into an isolated environment.
7. Dependencies, server configuration, patching, resource limits, and alerts have been reviewed; known material security failures are resolved.

Record evidence and remaining limitations with the relevant feature or deployment documentation. Passing checks reduces risk; it does not constitute a guarantee of security or a compliance certification. Public multi-user access and real trade execution require expanded threat models and a separate security review before activation.
