# Offline OIDC ID-token verification

OA3.2 adds signature and claim verification for a narrow, inactive OIDC profile. It builds on the [code-flow contracts](oidc-contracts.md). It does not add login routes, fetch keys, consume attempts, resolve owners, establish browser sessions or switch authentication providers.

## Trusted input and output

`verify_id_token` receives a redacted compact token, a caller-supplied trusted JWKS snapshot, the original login attempt, an explicit current UTC epoch time, and an optional redacted access token for hash verification. The future acquisition layer must bind that key snapshot to the fixed issuer using verified HTTPS and bounded retrieval. Accepting arbitrary user-supplied JWKS would defeat signature trust; this offline function does not establish key provenance.

Only successful cryptographic and policy validation produces immutable, redacted evidence: exact issuer/opaque subject, client audience, issuance, expiry, authentication time and authentication methods. No token, nonce, provider-session identifier, key material or financial owner appears in that result. The public result type is a protocol, not a public evidence constructor. Like other internal Python results, it is not a security capability; application authorization still requires explicit owner mapping and live session checks.

Malformed trusted key configuration raises generic authentication-unavailable errors. Invalid, unsupported or unauthorized tokens raise generic authentication-denied errors. Payloads, provider claims and key bytes are not copied into errors or logs. There is no network access, automatic key refresh, key cache or unknown-key retry.

## Supported profile

| Boundary | Enforced behavior |
| --- | --- |
| Algorithm | RS256 only, selected by the application rather than negotiated from a token |
| Public keys | RSA 2048, 3072 or 4096 bits; exponent 65537; no private parameters, certificate URLs or embedded certificates |
| Key selection | Mandatory bounded `kid`; at most eight uniquely identified keys in an explicitly supplied snapshot; no duplicate JSON fields |
| JWK metadata | Only the documented public RSA fields; optional `alg=RS256`, `use=sig` and `key_ops=[verify]` must agree with signature verification |
| JOSE header | Only `alg`, `kid` and optional `typ=JWT`; token-provided keys/URLs, critical extensions, unencoded payloads and compression are rejected |
| Sizes | Compact token at most 16 KiB; decoded header 2 KiB, payload 8 KiB; trusted JWKS 64 KiB; bounded key count and RSA signature size |
| Encoding | Strict UTF-8 JSON objects and canonical unpadded base64url; duplicate fields, nonfinite/fractional numbers and unsupported nesting fail closed |
| Identity | Exact configured issuer, opaque subject and one exact client audience; a one-item audience array is also accepted; optional authorized party must equal that client |
| Correlation | Exact signed nonce from the original, still-live attempt |
| MFA profile | Exactly `pwd`, `otp` and `mfa` in the signed AMR list, with no duplicates; order is immaterial |
| Optional access-token hash | A present `at_hash` requires the supplied bounded ASCII access token and a valid hash checked by Authlib's OIDC implementation |

The AMR rule is an initial TOTP-only offline profile, not a universal equivalence between an MFA label and sufficient assurance. Other factor combinations and additional claims are rejected. Actual signed claims and authentication freshness must be demonstrated against the pinned Authelia release and dedicated client before integration. An `aal2`, email or group claim is not an ownership or assurance substitute. [Authelia AMR definitions](https://www.authelia.com/reference/guides/authentication-method-references/).

The accepted claims are `iss`, `sub`, `aud`, `exp`, `iat`, `auth_time`, `nonce`, `amr`, and optional `azp`, `nbf`, `at_hash`. Extra profile/group/custom claims are outside this initial profile. If no `at_hash` exists, this verifier makes no claim that an accompanying access token is bound to the identity token.

## Time and replay boundaries

All time values are strict integer UTC epoch seconds; booleans and floating-point values are rejected. Authentication time must not follow issuance, issuance must precede expiry, and a present not-before value must precede expiry. Token lifetime is at most one hour. An expired token is rejected with no expiry grace.

At most thirty seconds of forward clock skew is tolerated for issuance, authentication time and not-before. Issuance cannot predate attempt admission by more than thirty seconds. At callback verification, authentication age must be at most the attempt's original `max_age` plus thirty seconds. This is deliberately conservative: `max_age=0` accepts authentication at most thirty seconds old, so a delayed callback may require restarting sign-in. The original five-minute attempt deadline is never extended.

Authlib's claim validator does not alone enforce the application's authentication-age policy. The wrapper checks these bounds explicitly in addition to maintained JOSE/OIDC verification. Token renewal cannot reset freshness through this function; the original authentication time remains explicit evidence.

Signature and nonce checks do not consume an attempt or prevent replay of an otherwise valid token. The later durable authorization flow must claim state once before token exchange, retain consumption after uncertain exchanges, bind the browser, apply admission controls and serialize session issuance against local revocation. Tests here establish none of those database/browser properties. Provider logout, token introspection and IdP account changes also do not establish application-session revocation. [Migration contract](oracle-authelia-migration.md#identity-and-session-contract).

## Libraries and local evidence

The implementation uses `joserfc.jwt.decode` for signature verification with an explicit RS256 allowlist, followed by Authlib's `CodeIDToken` validator for OIDC checks including nonce, authorized party and optional access-token hash. No custom RSA or JOSE algorithm is implemented. A narrow typed adapter contains Authlib's currently untyped claim-validator API. [Authlib OIDC API](https://docs.authlib.org/en/stable/oauth2/specs/oidc.html), [release history](https://docs.authlib.org/en/stable/upgrades/changelog.html).

Local evidence on 10 November 2026 used a separate Python 3.14.9 scratch environment with binary-only Authlib 1.9.5 and joserfc 1.8.0 installations. Existing dependencies were aligned with the application's installed versions, including HTTPX2 2.16.0 and cryptography 50.0.2. That source verification did not modify the project environment. The integrated manifest and lock now pin Authlib 1.9.6 and joserfc 1.8.0 for this offline verifier; locked installation, current advisory auditing and the final integrated gate are recorded separately with the PR. No ARM installation or live Authelia compatibility is claimed.

The combined pure suites passed 276 tests: 128 earlier contract cases and 148 verification cases. Coverage includes signed-but-invalid claims, signature substitution, explicit key rotation, hostile JOSE/JWK metadata, duplicate JSON, precision/type bounds, clock/freshness boundaries, weak keys, access-token hashes and redacted results. Ruff lint/format and strict mypy for five OIDC modules passed. One initial weak-key test fixture triggered the library's security warning while preparing input; the fixture now encodes its public test numbers directly so the application rejection is exercised without suppressing warnings. Failure evidence is retained.


Authlib 1.9.6 addresses [GHSA-cg3f-7pqx-v33v](https://github.com/authlib/authlib/security/advisories/GHSA-cg3f-7pqx-v33v), which affects IDJAGGrant in versions 1.9.0 through 1.9.5. This verifier uses CodeIDToken and does not register that grant. The [upstream comparison](https://api.github.com/repos/authlib/authlib/compare/v1.9.5...v1.9.6) changes five files while leaving CodeIDToken and dependency declarations unchanged. This supports carrying forward the frozen verifier code; historical 1.9.5 tests are not execution evidence for 1.9.6. Fresh locked installation, advisory auditing and integrated checks remain required.
