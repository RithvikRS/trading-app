# INDmoney custom-client compatibility

Step 6A.2 records provider checks performed on 24 October 2026. Custom application registration and the authorization handoff worked. Authenticated portfolio access, complete transaction history and successful token renewal remain unverified. These findings support building the protected authorization boundary; they do not enable a connection or establish a complete import format.

See the [integration sequence](indmoney-integration-plan.md) and the [sanitized observation record](evidence/indmoney-compatibility-2026-10-24.json). The observation record contains statuses and capability checks, not provider response bodies or client credentials.

## Observed custom-client behavior

| Check | Result | Interpretation |
| --- | --- | --- |
| Fixed public OAuth discovery | Passed using the existing 6A.1 validator | The provider still advertises the expected resource, issuer, read scopes, PKCE and grant capabilities. |
| One custom-client registration | `POST https://mcp.indmoney.com/register` returned HTTP 201 | A local application could register without a financial-account login. This is stronger evidence than an advertised registration URL. |
| Registered metadata | Exact requested callback, `portfolio:read`, `client_secret_basic`, authorization-code and refresh grants were echoed | The application registration matches the requested shape. Echoed metadata is not proof of a granted account permission or successful token exchange. |
| Credential issuance | Client identifier and secret were issued | An application secret now needs custody even before any user grants account access. |
| PKCE handoff | A request with S256 PKCE, random state and the resource parameter returned HTTP 302 to an INDmoney HTTPS address | The custom client reached the provider handoff. No redirect was followed; the sign-in page, consent, code return and token exchange were not tested. |
| Unissued refresh-token rejection | One request to the fixed token endpoint returned HTTP 401 with no access/refresh token fields | The negative request produced no tokens. It does not prove successful client authentication, refresh-token validation, rotation or renewal. |

Registration used the descriptive name `Portfolio local development` and the exact callback `https://127.0.0.1:8443/api/v1/connections/indmoney/callback`. This address is consistent with the local HTTPS rehearsal origin, but the callback route is not implemented and the temporary rehearsal certificate is not a persistent browser-trusted identity. Registration does not make that callback operational. A hosted application needs its own verified callback and client configuration.

The registration response did not supply `client_secret_expires_at` or a client-management URI. Secret lifetime and application-registration removal/rotation therefore remain unresolved. Do not interpret an omitted lifetime as an unlimited lifetime, or token revocation as client-registration deletion. [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591) distinguishes registered client metadata from user authorization and defines the secret-expiry response field.

The handoff used only a newly generated state and PKCE challenge. No password, MPIN, OTP, TOTP seed, account identity or user access token was supplied. There was no authorization-code exchange, authenticated tool call or provider-side financial action. The refresh rejection used a clearly synthetic, never-issued value and the registered application's client authentication; no real refresh token existed.

## Local registration custody

The complete registration response was encrypted with Windows DPAPI for the current user before inspection. It remains only in ignored local `.cache/indmoney-client-probe/registration.dpapi`; it is absent from Git, CI, application configuration and the hosted database. A synthetic protect/unprotect round trip and subsequent local decryption for the handoff verified that custody mechanism. Only allowlisted boolean results and HTTP statuses were emitted.

Retain this single registration for controlled local follow-up. The registration probe records that a request was sent and refuses to create another when the earlier outcome or credential file exists. Do not repeat registration during tests or CI. An unknown response must be investigated before any replacement registration. There is no verified client-management deletion endpoint to invoke automatically.

DPAPI custody is local research custody, not the deployed credential design: access depends on the Windows user profile, and no recovery or rotation process for this client secret has been verified. Step 6B must establish encrypted application custody, ownership, callback protections and recovery before loading these credentials into an enabled connector. Do not print, paste into a conversation, or commit the encrypted or decrypted response. Reuse or retire the registration deliberately when its verified management path is available.

## Transaction-history assessment

| Interface | Documented capability | Import decision |
| --- | --- | --- |
| [INDmoney MCP guide](https://www.indmoney.com/mcp) | Holdings, portfolio summaries, SIP information and market-data tools. The published tool reference does not document a complete account transaction ledger. | Treat historical transactions as unverified. Price/candle history and SIP status cannot establish completed purchases, redemptions, fees, dividends or cash movements. Absence from this guide is not proof that no additional capability exists. |
| [INDstocks order and trade APIs](https://api-docs.indstocks.com/normal_orders/) | The order book and segment trade book are described as current-trading-day views. Per-order fills require an order identifier; no backfill retention guarantee is stated there. | These endpoints do not establish a complete historical ledger or mutual-fund/US activity coverage. Do not substitute the separate trading interface for the read-only connection automatically. |

No authenticated `tools/list` response or financial payload was obtained. Consequently tool names advertised on a web page are candidates, not verified machine schemas. Native currencies, exact numeric encoding, folio/plan identifiers, account boundaries, source timestamps, pagination completeness, history dates and stable transaction identities remain open source-contract requirements. The next importer must reject unsupported evidence explicitly; it cannot infer transactions from changes in current holdings.

Keep statement fallback for missing historical evidence, external holdings and source reconciliation. No supported CAS layout is selected by this investigation. Snapshot-only intake may proceed only after real response contracts, owner/account mappings, coverage dates and review behavior are verified.

## Token renewal assessment

The public authorization metadata advertises a refresh grant and the registration response echoed it. The [MCP guide](https://www.indmoney.com/mcp) also describes short-lived sessions and reauthentication after expiry. Neither establishes a tested access-token lifetime, refresh-token lifetime, rotation policy, reuse detection, revocation propagation or unattended-renewal entitlement for this client.

The HTTP 401 negative probe is recorded as rejection only. Its result did not identify a standard `invalid_grant`, `invalid_client` or `unsupported_grant_type` value, so no more specific cause is inferred. In particular, correct Basic client-authentication interoperability remains part of the real token-exchange test. A failing token request cannot be reported as a successful renewal test.

INDstocks uses a separate mechanism. Its [authentication documentation](https://api-docs.indstocks.com/Users/) describes a 24-hour token and TOTP-based regeneration that invalidates the previous TOTP-generated token. This is not the MCP refresh-token contract. Do not transfer that lifetime or regeneration scheme to the portfolio connector, or store account MPIN/TOTP material to make renewal appear automatic.

## Remaining acceptance and next implementation

The public and unauthenticated portion of 6A.2 is complete. The authenticated portion depends on Step 6B's secured callback and credential custody, followed by owner-side sign-in. Keep those acceptance items open; fictional responses cannot close them. No account credentials or statements are needed in development conversations.

| Remaining check | Required evidence |
| --- | --- |
| Personal application use and retained data | Applicable provider terms/consent or a provider clarification covering the direct backend, storage and scheduled access. The [general terms](https://www.indmoney.com/terms-of-services) and [privacy policy](https://www.indmoney.com/privacy-policy) do not provide a custom-client retention contract. HTTP 201 is technical acceptance, not a storage license. |
| Safe account authorization | Current MFA and bound workspace context; single-use state/PKCE; exact issuer, resource and callback checks; scope validation; no callback-code logging; replacement-session and replay rejection. |
| Protocol and tool compatibility | Successful initialization and negotiated protocol version, bounded authenticated tool listing, reviewed input/output schemas and enforced read permissions. |
| Account and data coverage | Compare approved source records locally against provider holdings across the relevant markets and fund variants, preserving missing values and coverage limits. Check external advisor-fund linkage independently. |
| Successful renewal | Record token lifetime metadata without token values; perform a refresh; confirm post-refresh access, any replacement refresh token, and behavior near expiry. |
| Renewal races and disconnect | Serialize refresh, test stale-result rejection, controlled reuse/expiry and provider revocation without retry loops. Keep local access disabled even if provider revocation is unavailable. |
| History and reconciliation | Verify complete supported date ranges, pagination and stable source IDs, or explicitly retain snapshot-only coverage and statement fallback. |

Step 6B can implement the protected authorization boundary with synthetic tests while these provider checks remain open. Live financial import and scheduling stay disabled until their own acceptance is complete. This documentation change adds no runtime endpoint, database state or trading capability; the local research registration is the only new provider-side application record.
