# Authentication design

## Scope and security boundary

Trace supports GitHub OAuth, Google OpenID Connect, and verified email/password accounts. Authentication is browser-cookie based. The API is the only issuer and verifier of Trace session credentials; provider credentials are never returned to the browser.

## Session contract

An authenticated browser receives two HttpOnly cookies:

| Credential | Format | Lifetime | Purpose |
| --- | --- | --- | --- |
| Access token | Ed25519-signed JWT | 60 minutes | Identifies the user and session for API requests. |
| Refresh token | 256-bit opaque random token | 7 days | Rotates the session and obtains a new access token. |

The JWT contains `iss`, `aud`, `sub`, `sid`, `jti`, `iat`, `nbf`, `exp`, and `token_use=access`. It uses only `EdDSA`; verification rejects every other algorithm, unexpected issuer/audience, malformed UUID, or expired token. It contains no email address, provider credential, or authorization decision.

`auth.sessions` is the session authority. `auth.refresh_tokens` stores only an HMAC digest of a refresh token. Refreshing consumes the old token and creates its replacement in one transaction. Reuse of an already consumed token revokes its entire session before returning a generic authentication failure. Every protected request verifies that `sid` is still active, so logout, password reset, and account disablement invalidate access tokens immediately rather than waiting up to 60 minutes.

Logout revokes the current session and all of its refresh tokens, clears the three browser cookies, and returns `204` whether or not the browser has a usable token. Password reset revokes every session for the account.

## Browser transport, CORS, and CSRF

Cookies have no `Domain` attribute and are therefore host-only. Production access cookies use the `__Host-` prefix and refresh cookies use `__Secure-`.

The approved production frontend origins are exactly:

- `https://trace.fortunealebiosu.dev`
- `https://traceai.vercel.app`

Because `traceai.vercel.app` can be cross-site relative to the API host, production cookies use `Secure; SameSite=None`. CORS allows credentials only from those exact origins and never permits a wildcard origin. Unsafe authenticated requests must include the non-HttpOnly CSRF cookie value in `X-CSRF-Token`; the value is HMAC-bound to the current session and compared in constant time. Requests with a missing, mismatched, or invalid CSRF token return `403 csrf_validation_failed`.

Development may use `SameSite=Lax` and `http://localhost:5173`; it must not use `SameSite=None` without HTTPS.

## OAuth

GitHub and Google use authorization-code flow with PKCE `S256`.

| Provider | Local callback | Requested identity scopes |
| --- | --- | --- |
| GitHub | `http://localhost:8000/auth/oauth/github/callback` | `read:user`, `user:email` |
| Google | `http://localhost:8000/auth/oauth/google/callback` | `openid`, `email`, `profile` |

At OAuth start, Trace generates a 256-bit state value, PKCE verifier, and, for Google, an OIDC nonce. Redis stores the transaction under an HMAC-derived state key for ten minutes: provider, PKCE verifier, nonce, user-agent hash, and an allowlisted post-login destination. The callback atomically consumes the transaction before exchanging its authorization code.

Google ID tokens must be verified against the provider JWKS with the expected signature, issuer, audience, expiry, nonce, subject, and verified email. GitHub identity is read only from the provider API after a successful code exchange. A provider identity is never automatically linked to an existing password account based solely on matching email. Linking requires an already authenticated account owner.

Provider access or refresh tokens are discarded after sign-in unless Trace needs to call that provider later. Retained tokens use Vault Transit AES-256-GCM encryption by default. Vault retains the encryption key; Trace stores only Vault ciphertext, the Vault key version, the encryption provider, and a key reference in `private.credentials`. Vault Transit receives authenticated context bound to credential ID, owner ID, provider, and credential kind, so ciphertext cannot be moved between those records.

`AUTH_CREDENTIAL_ENCRYPTION_PROVIDER=local` is an explicit offline-development fallback only. It uses a versioned AES-256-GCM key from `AUTH_CREDENTIAL_ENCRYPTION_KEY`; it must not be selected for a production deployment. The Vault setup, local-only constraints, and eventual HCP migration path are documented in [Vault Transit](vault-transit.md).

## Email/password, verification, and recovery

Passwords use Argon2id with a minimum 12-character policy and a 1024-byte upper bound. Password accounts must have `email_confirmed_at` before sign-in succeeds.

Registration creates a single-use email-verification token. Recovery requests always return `202` with the same generic response, whether or not an eligible account exists. Verification and recovery tokens are 256-bit random values, stored only as purpose-bound HMAC digests. Verification tokens expire after 24 hours; recovery tokens expire after 15 minutes. Both are consumed atomically.

The same transaction that creates either token also creates an `auth.email_delivery_jobs` record. Its payload is encrypted with the dedicated Vault Transit email key; RabbitMQ receives only the job UUID. The email worker uses durable publish confirmations and manual acknowledgements, then retries transient SMTP failures through three fixed delay queues. After `AUTH_EMAIL_MAX_RETRIES` (three by default), terminal work is routed to `trace.email.dead-letter` for operator inspection. See [Queueing Convention](queueing.md) for the topology and recovery rules.

The recovery link carries its token in a URL fragment. The frontend submits it in the confirmation request body over HTTPS, avoiding query-string and referrer leakage. A successful reset changes the password, consumes outstanding recovery tokens, revokes all sessions, and requires fresh authentication.

## Rate limits

The shared Redis token-bucket utility is the only authentication rate limiter. Redis server time and a Lua script make updates atomic. Redis failure is fail-closed for authentication flows and returns `503 auth_temporarily_unavailable`.

| Policy | Capacity/refill |
| --- | --- |
| `auth.login.ip` | 20 per 15 minutes |
| `auth.login.identity` | 5 per 15 minutes |
| `auth.registration.ip` | 10 per hour |
| `auth.password_recovery.ip` | 5 per hour |
| `auth.password_recovery.identity` | 3 per hour |
| `auth.oauth_start.ip` | 10 per 10 minutes |
| `auth.refresh.session` | 30 per 5 minutes |

Keys contain HMAC digests of IP, normalized identity, or session context, never their raw value. A rejected request receives `429 rate_limited` and an accurate `Retry-After` header.

## Error and audit contract

All API errors have this shape:

```json
{
  "error": {
    "code": "authentication_failed",
    "message": "Unable to complete authentication.",
    "request_id": "uuidv7"
  }
}
```

The client never receives passwords, session tokens, JWTs, OAuth codes, OAuth state, provider errors, provider tokens, reset tokens, raw database errors, or stack traces. OAuth callbacks redirect to the frontend with a generic error code and request ID only.

| Failure category | Client result | Audit reason |
| --- | --- | --- |
| Unknown account, incorrect password, disabled account, or unverified account | `401 authentication_failed` | `invalid_credentials` or `account_not_eligible` |
| Missing, invalid, expired, or revoked access token | `401 authentication_required` | `token_invalid` |
| Invalid, expired, or reused refresh token | `401 session_expired` | `refresh_invalid_or_reused` |
| Invalid OAuth state, callback, code exchange, or ID token | Generic OAuth failure | `state_invalid`, `callback_malformed`, `code_exchange_failed`, or `id_token_invalid` |
| Invalid recovery or verification token | Generic invalid-token result | `one_time_token_invalid` |
| CSRF failure | `403 csrf_validation_failed` | `csrf_invalid` |
| Rate limit exceeded | `429 rate_limited` | `policy_exceeded` |
| Redis, database, mail, provider, signing, or encryption outage | `503 auth_temporarily_unavailable` | `dependency_unavailable` |

Every audit record includes a bounded event name, outcome, reason, request ID, route, HTTP status, and optional provider/policy/exception class. It includes keyed hashes—not raw values—for IP address, user agent, and account identity. It never records request bodies, credentials, or tokens. Retain detailed authentication audit events for 90 days with restricted access; alert on refresh-token reuse, repeated CSRF failures, provider configuration errors, and sustained rate-limit breaches.

## Required production configuration

Before serving requests, the application validates base64url-encoded 32-byte values for:

- `AUTH_JWT_PRIVATE_KEY`
- `AUTH_TOKEN_HASH_KEY`
- `AUTH_CSRF_HMAC_KEY`
- `AUTH_AUDIT_HASH_KEY`

When `AUTH_CREDENTIAL_ENCRYPTION_PROVIDER=local`, it additionally requires `AUTH_CREDENTIAL_ENCRYPTION_KEY`. When the provider is `vault`, it instead requires `AUTH_VAULT_ADDR` and `AUTH_VAULT_TOKEN`; production requires an HTTPS Vault address.

Production additionally requires secure cookies, the approved cookie prefixes, `SameSite=None`, and exactly the two production frontend origins above. The service deliberately refuses to start on an incomplete or insecure configuration.
