# OIDC code-flow contracts

OA3.1 introduces inactive, pure contracts for the future Authelia authorization-code flow. No authentication route, identity-provider call, database state or browser session is added. The implemented Supabase authentication remains unchanged.

## Implemented boundary

`trading_oidc` accepts explicit trusted client configuration with HTTPS issuer, authorization/token/JWKS destinations and an exact callback. Provider endpoints must share the configured issuer authority. This first profile supports canonical ASCII DNS/IPv4 authorities and simple paths; unsupported forms are rejected without normalization. Issuer comparison remains exact, including a trailing slash. No discovery, environment loading, credentials or network client exists here.

A server-side attempt holds independent random state, nonce, S256 PKCE verifier and browser-correlation values. Version 1 has a fixed five-minute lifetime from admission; timestamps and version are strict integers. The requested authentication age is explicit, from zero through five minutes. Generating an attempt does not persist it or reserve admission capacity.

The request builder emits only the fixed authorization-code/query profile with `openid`, state, nonce, S256 challenge, exact callback and authentication-age requirement. It requests essential `amr` and `auth_time` claims. The returned URL has a redacted representation. Requesting these claims establishes neither MFA nor freshness; later signed-token verification must enforce both.

The callback parser accepts bounded raw query bytes, requires state and RFC 9207 issuer identification, and permits exactly one code or error outcome. Duplicate fields, unknown fields, invalid encodings and excessive values fail closed. Error descriptions and error URLs are discarded. A separate pure check compares state, browser correlation, exact issuer and attempt lifetime.

`IdentityAnchor` is an unverified address consisting of exact issuer and opaque, case-sensitive subject text. It grants no authority, resolves no owner and assumes no UUID subject, provider session ID, email, factor identifier or Supabase `aal2` claim. Unsupported subject forms are rejected rather than repaired.

All sensitive containers have redacted representations and failures reuse generic authentication errors. These helpers do not log protocol values.

## Boundaries still required

Callback parsing and correlation are not authentication and do not prevent replay by themselves. Durable storage must atomically claim a still-live attempt before code exchange, preserve that consumed state after uncertainty, and enforce admission limits. The future HTTP route must independently verify the exact callback method/path, trusted origin/host, navigation shape, duplicate headers/cookies and absent body. Ordinary CSRF protections and the main Strict session cookie must remain intact; a separate short-lived Lax correlation cookie can support the selected cross-site GET callback.

The next increment must verify signatures with a maintained library and bounded trusted JWKS, then enforce issuer, audience/authorized party, nonce, expiry, authentication time and the selected MFA assurance. It must not trust token-supplied keys or key URLs. Explicit owner enrollment, provider revalidation, encrypted session custody, revocation, offboarding and Oracle-backed isolation remain separate integration work. No live identity service compatibility is established by the pure tests.

Initial research used Authlib 1.9.5 with HTTPX2 support. A binary-only dependency dry run against Python 3.14.9, HTTPX2 2.16.0 and cryptography 50.0.2 resolved Authlib 1.9.5 and joserfc 1.8.0 without replacing existing packages. A separate offline-verifier scratch environment subsequently installed those exact candidates and ran its pure suites. Neither dependency is added by this increment. The next integration selects Authlib 1.9.6 with joserfc 1.8.0 to address [GHSA-cg3f-7pqx-v33v](https://github.com/authlib/authlib/security/advisories/GHSA-cg3f-7pqx-v33v). That advisory concerns IDJAGGrant; the planned verifier uses CodeIDToken. The [five-file upstream comparison](https://api.github.com/repos/authlib/authlib/compare/v1.9.5...v1.9.6) leaves CodeIDToken and dependency declarations unchanged. The original 1.9.5 results remain historical; installation, current advisory auditing, ARM compatibility and final integrated acceptance of 1.9.6 remain separate work. See [Authlib releases](https://docs.authlib.org/en/stable/upgrades/changelog.html) and [HTTPX2 integration](https://docs.authlib.org/en/stable/oauth2/client/http/httpx.html).

## Verification

Focused pure tests exercise fixed request construction, PKCE, random secret separation, exact deadlines and versions, hostile callback/configuration inputs, correlation mismatch, opaque identity preservation and safe representations. No provider, database, HTTP route or browser tests are represented by this coverage. The [migration plan](oracle-authelia-migration.md) records the wider acceptance sequence.

Local source verification on 10 November 2026: 128 focused pure tests passed, including the [RFC 7636 Appendix B](https://www.rfc-editor.org/rfc/rfc7636#appendix-B) PKCE vector. Ruff lint/format and strict mypy for all four modules passed. The final integrated repository gate remains separate.
