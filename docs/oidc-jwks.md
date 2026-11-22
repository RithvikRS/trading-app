# Fixed-issuer JWKS reader

OA3.3 adds a bounded public-key reader and an in-memory cache for the offline OIDC verifier. It performs no discovery, token exchange, owner resolution, callback handling, session creation, scheduled task, database write or automatic application activation. Its tests use mock transports and the installed HTTPX2/HTTPcore2 parser over a fake no-socket network backend. They perform no provider DNS resolution, network connection or TLS handshake.

## Configuration and use

JwksReader is constructed once for an exact OidcClient configuration. Its asynchronous read(client) method requires the same configuration and returns validated public JWKS bytes that are fresh at delivery. Pass those bytes directly to verify_id_token with the same login attempt client. Do not persist returned bytes or keep using them after a later failed read. Returning bytes is an internal trust contract, not a capability that prevents trusted application code from misusing them.

Each reader has one private snapshot; readers do not share snapshots, even for equal client configurations. Changing the issuer, JWKS URL, client ID, callback or other configured endpoints requires a new reader. Deployments must create a bounded number of these internal readers, normally one per worker for the configured client. No reader registry is keyed by browser input.

The URL is the explicit HTTPS jwks_uri already validated by OidcClient. Token headers, callbacks, response bodies and redirects cannot select another destination. No discovery URL or kid parameter is accepted. Operator-configured private DNS is permitted for self-hosted deployments; this is normal HTTPS trust in a configured endpoint, not DNS/IP pinning or a general-purpose URL fetch facility.

The optional transport factory and clock are trusted test seams. They must never be supplied from browser or provider data. Production uses the fixed HTTPX2 configuration: verified TLS, no environment proxies or CA overrides, no redirects, HTTP/1.1, one connection, no keepalive, no retries, and no credentials. Every fetch creates and closes its own client. Set-Cookie responses are rejected, and the owned cookie jar is cleared during cleanup.

## Request and response bounds

| Limit | Value |
| --- | --- |
| Concurrent network operations | One per process, with immediate rejection when busy |
| Request and body deadline | 10 seconds |
| Connect/read/write inactivity timeout | 3 seconds each |
| Pool wait timeout | 1 second |
| Cleanup deadline | 3 seconds |
| Parsed response header fields | At most 64 and 16 KiB combined names/values after HTTP normalization |
| Response body | 1 through 65,536 bytes |
| Raw body chunks consumed by reader | At most 4,096 bytes |
| Public keys | 1 through 8 |
| Maximum cache lifetime | 60 seconds from request admission |
| Response-policy/schema rejection cooldown | 30 seconds per reader; ambiguous transport failures latch admission |

The application header budget applies to parsed fields exposed by HTTPX. The maintained h11 parser consolidates identical repeated or comma-list Content-Length fields before these checks, so equivalent normalized framing is accepted. Conflicting lengths are rejected by that parser; duplicate critical fields that remain visible are rejected by the reader. The 64-field/16-KiB budget is therefore not a raw-wire header limit. The installed transport has its own HTTP/1.1 buffering controls; no preallocation or total-memory bound is claimed here. Deadlines use cooperative asynchronous cancellation, not forced termination of non-cooperative code or operating-system calls.

Only a complete 200 response is accepted. Media type must be application/json or application/jwk-set+json, optionally with UTF-8 charset. Compression, partial responses, duplicate critical fields preserved after parsing, conflicting framing, redirects and cookies fail closed. Content-Length is canonical bounded decimal and must match actual bytes. Chunked transfer encoding is allowed only without Content-Length. The response is streamed as raw bytes, and the unchanged offline verifier's strict key validator runs before publication.

There is no HTTP retry loop. A request sends Cache-Control no-cache to request upstream revalidation. Unknown status codes, 429, 503, malformed JSON, transport errors and unsupported key sets produce the same generic AuthenticationUnavailable error. The response body and transport exception text are not exposed in public exceptions.

## Cache freshness and failure behavior

A complete validated document replaces the previous snapshot atomically. Removed keys are not retained by merging old and new documents. Cache lifetime starts when network custody is acquired, so transport, validation and cleanup time consume its lifetime. Cache hits do not extend expiry. An expired snapshot is never returned after a failed refresh.

Time is read from a monotonic clock. Invalid, nonfinite, negative, implausibly large or regressing clock values clear the snapshot and latch that reader unavailable. No wall-clock conversion, HTTP-date parsing or persisted expiry is used.

Cache-Control can shorten retention but cannot extend it beyond 60 seconds. A canonical max-age below that limit shortens it; zero, no-store, no-cache, duplicate directives, unsupported directives or malformed directives disable reuse. Bare public, private and must-revalidate are supported. A noncacheable response may be returned only for its current read and is not retained. A bounded Age field reduces remaining lifetime; stale or malformed age is rejected. A noncacheable response with positive Age is conservatively rejected.

This is a restricted application key-cache policy, not a general HTTP cache. ETag, 304, Expires, stale-if-error and stale-while-revalidate are not implemented. There is no background refresh. Rejected reads clear the local snapshot and impose a 30-second per-reader cooldown. Response-policy or schema rejection can recover after that cooldown when cleanup succeeds. Request/body transport failures and active-fetch cancellation additionally latch process-wide network admission as described below. Cold/expired concurrent requests fail immediately instead of building a queue; unrelated fresh snapshots need no network admission.

Network custody remains held through raw-iterator, response and client cleanup. The raw iterator closes in the same task, and a guarded stream observes explicit stream-close failures. However, the maintained HTTP transport may mark a connection closed and remove it from its pool before an internal close finishes. A successful later response/client close cannot prove that this hidden cleanup succeeded.

For that reason, any exception from the awaited request or body iteration, including timeout or active-fetch cancellation, immediately disables process-wide network admission. Failed, timed-out or interrupted final cleanup also disables it. A replacement reader cannot reopen admission. External task cancellation is preserved even when an internal cleanup failure replaces CancelledError with another exception.

This is a deliberately conservative availability tradeoff: an ordinary transient connection failure or a cleanly cancelled active fetch also requires process restart before new network reads. It is not limited to confirmed socket leaks. Investigate the cause before restart; future callback integration must account for this behavior. Response-policy/schema rejection with successful cleanup retains the ordinary cooldown instead. Existing fresh snapshots may still be read until their normal expiry. No detached fetch or cleanup task is created.

The code emits no provider logs. Exceptions and object representations exclude endpoints, response bodies, keys and cookies. The application's existing SafeFormatter suppresses raw third-party transport messages and arguments. A standalone caller that replaces logging or adds HTTP tracing must preserve that privacy boundary.

## Supported issuer profile and rotation

The reader retains OA3.2's narrow profile unchanged: RSA RS256 signing keys only; exponent 65537; 2048/3072/4096-bit canonical moduli; unique bounded key IDs; no private material, certificate metadata, unsupported fields or mixed algorithms anywhere in the document. The reader reuses the existing internal key validator rather than maintaining a second parser.

Authelia can publish keys for other algorithms and can add x5c/x5t when certificate_chain is configured. Such documents are unsupported by this profile. They are rejected as a whole, without silently filtering keys or fields. Compatibility with the actual shared issuer still needs verification; this increment does not change that issuer's configuration. See [Authelia provider configuration](https://www.authelia.com/configuration/identity-providers/openid-connect/provider/).

Unknown key IDs are denied by the offline verifier and never trigger an additional network request here. The operational requirement is to publish a new signing key for longer than the 60-second cache window before using it, and retain retired keys during the outstanding token/attempt verification overlap. A key removed from the issuer may remain accepted from a previously fresh application snapshot for up to 60 seconds. This is not immediate key revocation or browser-session revocation.

[OIDC Core describes refetching keys when an unfamiliar key ID appears](https://openid.net/specs/openid-connect-core-1_0.html#RotateSigKeys). This increment deliberately relies on prepublication instead. A future bounded unknown-key refresh mechanism needs separate review if that operational requirement cannot be guaranteed.

## Verification and remaining work

Synthetic tests cover fixed URL/client binding; real transport construction without network; installed HTTPX2/HTTPcore2 parsing over a fake no-socket backend, including internally hidden close failures and normalized framing; TLS/proxy/retry/connection settings; stream/header/body/key limits; strict key compatibility; cache expiry and replacement; upstream cache hints; no stale fallback; no unknown-key refetch; failure cooldown; nonqueued concurrency; cancellation and cleanup latches; clock uncertainty; cookie clearing; and redacted failures. The existing OIDC contract/verifier cases also run against the new module's environment.

The historical candidate-two tests used Authlib 1.9.5 and joserfc 1.8.0. The preceding offline-verifier integration now selects patched Authlib 1.9.6 with joserfc 1.8.0; no dependency or lock selection changes belong to this increment. Historical tests are not execution evidence for the patched library. Fresh locked checks and the serialized full integration gate remain separate from those focused mocked results.

[OA3.4 code exchange](oidc-code-exchange.md) adds a separate bounded adapter and reran all four OIDC suites under Authlib 1.9.6: 589 cases passed, including the 130 JWKS cases. This is patched-library scratch evidence, separate from final integrated acceptance. Its independent exchange gate and this reader's gate permit two concurrent OIDC network operations per worker. Each gate conservatively requires process restart after its own transport uncertainty; single-send exchange does not establish durable replay protection.

Still pending: actual Authelia endpoint and header compatibility, certificate/reverse-proxy behavior, ARM runtime acceptance, multi-worker resource limits, rotation rehearsal, durable single-use attempts and code-exchange orchestration, callback routes, provider MFA evidence, owner binding, browser sessions, recovery/offboarding and deployed operational validation.

Transport references: [HTTPX2 timeouts](https://pydantic.dev/docs/httpx2/advanced/timeouts/), [environment variables](https://pydantic.dev/docs/httpx2/api/environment_variables/) and [transport controls](https://pydantic.dev/docs/httpx2/advanced/transports/).
