# Authentication options

Research snapshot: 22 October 2026. This is a design comparison, not a configured authentication service. The provider remains undecided. Local PostgreSQL for development and Supabase PostgreSQL for deployment remain selected regardless of the authentication choice.

## Requirements shared by every option

One explicitly provisioned owner, closed public registration, enforced MFA, protected server-side sessions, revocation, and tested recovery. Login must never grant financial access before all required factors complete. The API derives ownership from authenticated identity; email addresses, browser-supplied owner IDs, and mutable profile metadata cannot grant access. A private deployment entry point supplements application authorization.

The browser receives an opaque session cookie rather than provider access/refresh tokens. Authentication state is not stored in local storage or URLs. This requires an application session layer even when a provider handles credentials. Session limits, logout, and authorization must be tested in the Python application, not inferred from a provider dashboard.

## Comparison

| Option | Strengths for this project | Responsibilities and tradeoffs | Cost direction |
| --- | --- | --- | --- |
| Supabase Auth with FastAPI | Fits the existing architecture direction and planned database provider; credential verification and MFA service run off the Oracle VM | Python must safely integrate login/MFA, token renewal, revocation, and opaque application sessions. Provider outage affects login; database and identity share a provider. Recovery and email delivery need an explicit design | Free includes basic MFA; provider session timeouts, single-session controls, and leaked-password protection are not included on Free. Pro is currently listed from USD 25/month, before applicable usage/add-ons |
| Django with django-allauth | Python-managed accounts, database sessions, TOTP, recovery codes, WebAuthn, and headless interfaces for the existing React UI | Changes the provisional FastAPI/SQLAlchemy/Alembic direction to Django and its ORM/migrations. The project operates credential storage, MFA secret protection, email, abuse controls, recovery, updates, and backups | No managed authentication subscription; hosting, email, maintenance, and security operations still have costs |
| Auth0 with FastAPI | Hosted login and a separate managed identity service, with OIDC integration into the Python API | Another provider, configuration surface, and outage dependency. MFA factor availability, logout behavior, redirect handling, and recovery must match the chosen tier | Current B2C listing: Essentials USD 35/month for up to 500 active users includes Pro MFA factors; Free lists passkeys but excludes those MFA factors |

Plan features and prices are snapshots, not spending commitments. Verify the exact project/tenant entitlement before configuring a service. Sources: [Supabase pricing](https://supabase.com/pricing), [Django sessions](https://docs.djangoproject.com/en/5.2/topics/http/sessions/), [allauth MFA](https://docs.allauth.org/en/latest/mfa/introduction.html), [allauth headless](https://docs.allauth.org/en/latest/headless/introduction.html), and [Auth0 pricing](https://auth0.com/pricing).

## Credential and privacy boundary

With the proposed Supabase server-side login flow, the API handles password/MFA inputs transiently and forwards them to the provider; they must never be persisted or logged. Auth0 hosted login keeps password entry at the provider and returns a verified authorization result to the application. Django/allauth handles authentication in the Python application; with the selected hosted topology, its protected authentication tables would still reside in Supabase PostgreSQL. Self-managed authentication therefore does not mean all data stays on the Oracle VM.

Managed identity receives login identity and security metadata; financial records should not be sent as identity-profile fields or telemetry. Every option still needs secure local application sessions, authorization, database access, backups, and incident recovery. Choosing a provider is not a security certification.

## Supabase Auth implications

Supabase supports TOTP and phone MFA with an assurance-level claim. The baseline candidate is password plus authenticator-app TOTP, with the API requiring verified `aal2` before normal application access. The enrollment/recovery state is separate and restricted. Provider tokens must be verified, not merely decoded. Supabase also documents passkeys; their precise assurance, fallback, recovery, and Python/server-session behavior need evaluation before replacing this baseline. [MFA](https://supabase.com/docs/guides/auth/auth-mfa), [passkeys](https://supabase.com/docs/guides/auth/passkeys).

App-controlled idle/absolute expiry and immediate app logout remain necessary. Supabase's provider session limits are paid features, and a valid signed JWT alone does not prove its backing session has not been revoked. The implementation must explicitly verify upstream session validity and fail closed where that check is required; it must not promise immediate upstream revocation based on signature checks alone. [Sessions](https://supabase.com/docs/guides/auth/sessions), [server-side validation](https://supabase.com/docs/guides/auth/server-side/advanced-guide).

Keep refresh credentials encrypted server-side with separately held keys, serialize concurrent refresh attempts, and remove local access immediately on logout even when provider revocation fails. Provisioning/recovery uses separate privileged access; no service-role credential belongs in the normal browser or API request path. Default email delivery is limited and is not a production recovery plan. Confirm SMTP, verified sender, redirect allowlists, recovery-factor behavior, and account administration before use. Do not assume recovery codes exist for the selected provider flow. [SMTP guidance](https://supabase.com/docs/guides/auth/auth-smtp).

## Django implications

Django would become the single Python application; do not add it solely as a second authentication service beside FastAPI. Preserve React, local PostgreSQL, hosted Supabase PostgreSQL, and the ownership/RLS design. Use database-backed sessions; a signed browser cookie containing session data is not the selected storage model. [Django sessions](https://docs.djangoproject.com/en/5.2/topics/http/sessions/).

Use allauth's existing MFA and recovery capabilities instead of implementing password hashing, TOTP, or WebAuthn protocols. MFA enforcement is still a project policy. Its adapter supports encrypting stored TOTP secrets; key custody and rotation must be designed rather than assuming database fields are encrypted by default. WebAuthn requires explicit configuration and tests. [MFA features](https://docs.allauth.org/en/latest/mfa/introduction.html), [secret-encryption adapter](https://docs.allauth.org/en/latest/mfa/adapter.html).

This option gives more operational control and less dependence on a hosted login service, but an application-host compromise can expose the authentication data and decryption capability it uses. Patch cadence, failed-login protection, email security, recovery controls, and restore exercises become direct project responsibilities.

## Auth0 implications

Use hosted login with Authorization Code and PKCE through a maintained Python integration. Validate state, nonce, issuer, audience, signature, expiry, and required authentication strength; restrict redirect URLs. Keep resulting tokens server-side and apply the same opaque application session contract. Verify these requirements against the chosen SDK/tenant before implementing.

Do not infer that Free passkey availability establishes the exact required mandatory-factor and recovery policy. Verify user verification, fallback paths, factor removal, and actual assurance evidence. Its current MFA pricing makes it a less economical starting point for one personal owner. Provider features never replace database ownership checks.

## Recommendation and selection boundary

Supabase Auth remains the recommended fit for the current FastAPI direction when managed identity and low VM overhead are the priorities. This is an architectural judgment, not a claim that its free tier supplies every security control. Django/allauth is the strongest alternative here if owning the authentication lifecycle matters more than reducing operational responsibility. Auth0 is a reasonable managed alternative when hosted login and its paid feature set justify the recurring cost.

Choose the authentication and framework direction before Step 3A, since choosing Django changes the scaffold and migration tooling. Then record one short decision with provider/tier, primary factors, recovery method, local test approach, session implementation, and key custody. The [foundation plan](foundation-plan.md) defines the shared security contract and implementation increments; it does not provision any of these options.
