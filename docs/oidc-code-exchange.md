# Bounded OIDC code exchange

OA3.4 adds an inactive authorization-code exchange adapter for the configured confidential OIDC client. It adds no route, discovery, durable attempt store, owner lookup, browser session, refresh, userinfo, revocation call or automatic activation. Existing PostgreSQL and Supabase session behavior is unchanged.

## Interface and secret custody

Construct `CodeExchanger` with an exact `OidcClient` and `ClientSecretAuthentication`. The credential contains a redacted `SecretStr` and explicit `client_secret_basic` method. Optional clocks and transport factory are trusted test dependencies, never browser or provider inputs.

`await exchange(attempt, callback, browser_binding)` rechecks client, state, issuer, browser binding and original attempt lifetime before sending. Provider-error callbacks send nothing. It checks time again after cleanup and discards late successes. UTC must be a bounded integer; UTC and monotonic readings must be finite, nonnegative and nonregressing. Clock uncertainty latches that exchanger unavailable.

The immutable, redacted `UnverifiedTokenResponse` exposes ID token and access token as `SecretStr`, plus optional `expires_in`. It conveys no verified identity, enrollment, MFA or session authority. Explicit offline verification remains necessary. The access token stays opaque and is supplied to the verifier for its optional ID-token `at_hash` check.

Credentials come from trusted server initialization; secret loading, rotation and persistence remain separate. A future loader must enforce private single-link secret files and lifecycle controls. The adapter writes no payloads to disk and caches no tokens. It clears its mutable raw buffer and cookie jar, but Python strings and library buffers cannot guarantee zeroization. Redaction is not encryption. Preserve `SafeFormatter` and prohibit request/body tracing.

## Authentication and request profile

Only explicit `client_secret_basic` is supported. There is no challenge retry, negotiation, body-secret fallback, public-client fallback or second credential method. Configure the dedicated confidential Authelia client accordingly. [Authelia client authentication](https://www.authelia.com/configuration/identity-providers/openid-connect/clients/#token_endpoint_auth_method).

Authlib's Basic helper concatenates credentials before Base64 encoding; OAuth specifies form encoding first. This adapter therefore restricts client IDs to 1–100 RFC3986 unreserved ASCII characters and secrets to 43–128 URL-safe characters (`A-Z a-z 0-9 _ -`). These need no form escaping. Generate the secret independently with sufficient entropy; length checks do not prove randomness. Other characters are rejected. General credentials require a separately tested encoding adapter. [Authlib encoder](https://github.com/authlib/authlib/blob/v1.9.6/authlib/oauth2/auth.py), [RFC 6749](https://www.rfc-editor.org/rfc/rfc6749#section-2.3.1).

OAuth's security BCP prefers asymmetric client authentication. Basic is a deliberate limited initial profile. Moving to `private_key_jwt` needs separate assertion audience, lifetime, JTI, algorithm, key custody and rotation controls. [OAuth security BCP](https://www.rfc-editor.org/rfc/rfc9700#section-2.5).

Each invocation prepares at most one POST to the exact configured HTTPS token endpoint. The form contains only `grant_type=authorization_code`, original code, exact callback URI and original PKCE verifier. State, nonce, browser cookie, scopes and arbitrary browser headers are not forwarded. Basic is the sole authentication header; the client secret is absent from URL and form. The adapter uses Authlib's low-level request preparation instead of its buffered high-level token-fetch method, then owns bounded HTTPX2 transmission and parsing. [Request preparation](https://github.com/authlib/authlib/blob/v1.9.6/authlib/oauth2/rfc6749/parameters.py), [OIDC token endpoint](https://openid.net/specs/openid-connect-core-1_0.html#TokenEndpoint).

A fresh HTTPX2 client uses verified TLS, `trust_env=False`, no proxy, no redirects, HTTP/1.1, one connection, no keepalive and no retries. It requests JSON and identity encoding. Redirects, response bodies and token headers cannot select a destination. Operator-configured private DNS remains permitted under ordinary HTTPS verification; no DNS/IP pinning is claimed. Cookies are never reused.

## Bounds and response policy

| Boundary | Limit |
| --- | --- |
| Concurrent exchange network operations | One per process; immediate busy rejection |
| Request/body deadline | 10 seconds, capped by remaining attempt lifetime |
| Connect/read/write inactivity; pool wait | 3 seconds each; 1 second |
| Cleanup deadline | 3 seconds |
| Encoded request form | 1–8,192 bytes |
| Parsed response headers | 64 fields and 16 KiB combined names/values |
| Raw response body/chunks consumed | 1–65,536 bytes; chunks at most 4,096 bytes |
| ID/access token | Each 1–16,384 printable non-whitespace ASCII characters |
| JSON | Strict UTF-8 object, no duplicate keys; depth 4 and 16 members/items per container; no fractional/nonfinite numbers |
| Optional expires_in | Strict integer, 1–3,600 seconds; no session/MFA authority |

Header budgets apply after HTTPX/h11 normalization, not to raw wire bytes. Identical repeated or comma-list Content-Length fields can be consolidated and accepted; conflicting lengths fail in the maintained parser. Visible duplicate critical headers fail. These application parsing bounds are not a total-memory or preallocation guarantee. Deadlines use cooperative cancellation, not forced termination of blocking operating-system calls.

A complete HTTP 200 success requires ID token, access token and case-insensitive Bearer token type. Optional scope must be exactly `openid`. Refresh-token or error fields reject the success: refresh custody is absent. Bounded unknown extensions are discarded and never used as authority.

Content type must be `application/json`, optionally with UTF-8 charset. Compression, partial responses, cookies, conflicting framing and length/body mismatch fail closed. Chunked transfer requires absent Content-Length. Cache-Control requires `no-store`; its only other accepted directives are `no-cache`, `private`, `must-revalidate` and `max-age=0`, without duplicates. Pragma must be `no-cache`; Age must be absent or exactly zero. This narrow profile needs actual issuer compatibility evidence.

A bounded complete HTTP 400 `invalid_grant` response without token fields produces generic `AuthenticationDenied`. Other errors, 401, redirects, 429, 5xx, malformed/oversized responses and provider configuration failures produce generic `AuthenticationUnavailable`. Provider descriptions, response bodies and transport exception text are not exposed. Retry-After never triggers another send.

## Cancellation and availability

Authorization codes are single-use. Timeout, connection loss or cancellation cannot establish whether the provider consumed a code. Local cancellation cannot roll back an upstream exchange. There is no retry or speculative revocation; use a new authorization attempt after uncertainty. [RFC 6749 authorization codes](https://www.rfc-editor.org/rfc/rfc6749#section-4.1.2).

The process-wide exchange gate remains held through raw iterator, response and client cleanup. HTTPcore can remove a connection from its pool before hidden cleanup finishes; a later successful client close cannot prove that cleanup completed. Any exception from awaited send or body iteration, including timeout and active-fetch cancellation, therefore latches exchange network admission unavailable until process restart. Failed, timed-out or interrupted cleanup also latches it. Replacing the exchanger cannot reopen admission. External cancellation remains `CancelledError` even if transport cleanup replaces it with another exception. No detached network or cleanup task is created.

This conservative availability tradeoff applies even when a transient failure or cancellation actually cleaned up successfully. Investigate before restarting. Policy/schema rejection with successful cleanup allows a different attempt later; it does not make the rejected code reusable.

The exchange gate is separate from the unchanged JWKS gate. Their combined limit is two concurrent OIDC network operations per worker, multiplied by worker count. Multi-worker admission and rate controls remain integration work.

## Required durable integration

This class does not consume an attempt. Calling it twice can send twice; single-send applies to one invocation only. Before real callback use, atomically claim and commit a live, browser-bound attempt with durable replay prevention and admission/rate limits. Do not hold database locks over network I/O. Never reopen or extend a consumed claim after uncertainty, cancellation or crash.

After exchange, obtain trusted JWKS fresh at delivery and immediately run synchronous offline verification using the same attempt/client and current time. An optional readiness read before claiming can detect a known key outage, but discard those bytes and read again immediately before verification. There is no unknown-key retry. Key-read or verification failure after exchange still consumes the attempt.

Then resolve exact issuer and opaque subject through active enrollment, apply live owner/revocation checks and serialize session issuance against cancellation, logout and disablement. Callback method/path and proxy/host/origin trust, duplicate headers/cookies, fixed return destination, URL cleanup, correlation/main cookie policy, encrypted versioned custody, crash recovery and provider offboarding remain separate. Do not substitute OIDC data into Supabase session fields.

## Verification and limits

Synthetic tests cover request/authentication binding, encoding restrictions, parser/time/size limits, unknown extensions, errors, redaction, TLS/proxy/retry settings, framing, cookies, concurrency, cancellation, hidden close failures and explicit signed-token verification. They exercise installed HTTPX2/HTTPcore2 parsing over a fake no-socket backend as well as mock transports. They perform no provider DNS lookup, connection, TLS handshake or live authentication.

The focused environment uses Authlib 1.9.6, joserfc 1.8.0, cryptography 50.0.2 and HTTPX2 2.16.0. Earlier 1.9.5 contract/verifier/JWKS records remain historical; all four suites also ran with 1.9.6. That patch addresses the separate IDJAG grant; official comparison leaves CodeIDToken and dependency declarations unchanged. Version review does not replace execution or the integrated gate. Shared pin/lock integration is separate from this three-file increment. [Authlib release record](https://docs.authlib.org/en/stable/upgrades/changelog.html#version-1-9-6-2026-11-14), [official comparison](https://api.github.com/repos/authlib/authlib/compare/v1.9.5...v1.9.6).

Unperformed compatibility work includes selected Authelia release/client registration, required callback issuer, Basic encoding, response headers and absence of refresh tokens, AMR/auth_time behavior, RS256-only JWKS, certificate/reverse-proxy path, key rotation/prepublication, ARM installation, provider disable/revocation and multi-worker behavior. This increment does not establish deployment readiness.

Transport references: [HTTPX2 timeouts](https://pydantic.dev/docs/httpx2/advanced/timeouts/), [environment controls](https://pydantic.dev/docs/httpx2/api/environment_variables/) and [transports](https://pydantic.dev/docs/httpx2/advanced/transports/).
