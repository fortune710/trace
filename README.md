## Trace

Trace is AI agent that scans your vibe-coded apps for security vulnerabilities and pre-launch mistakes that could cost you or your users when you hit production. The agentic era has given anyone the ability to build an entire application end-to-end without needing technical or product expertise.

But to launch an app on any platform, there are technical, product and legal decisions to be made to prevent you or your users from being compromised. Trace exposes those gaps present in your app that need your attention before launching to the market.

Trace is built for the non-technical builders who lack the technical and product expertise for successfully launching in application on a production environment and into the market.


## System Architecture

On a high level, Trace will operate with the client-server model, with the server layer being a combination of a relational database, API server and a cache (for saving frequently accessed data). 


## Tech Stack 

- React: The library of choice for building the user interface for Trace, with the Typescript programming language. React was chosen because it the most popular library for building user-interfaces with huge community support.

- Fast API: The library of choice for building the API server, with the Python programming language. FastAPI makes it easy and flexible to build APIs in Python.

- PostgreSQL: The relational database of choice for storing data.

- Redis: The cache client for saving frequently-accessed data to improve API server performance.

- Langchain/Langgraph: For building and orchestrating AI agents and coordinating AI workflows.

- Langsmith: For adding observabilty to AI agent and workflow runs to ensure reliability of results and findings.

- Sentry: For error monitoring and observability of API serve and user interface to ensure reliability of the platform.

## Local services

Docker Compose runs the FastAPI backend, email worker, PostgreSQL, Redis, RabbitMQ, Mailpit, and a local Vault Transit service.

1. Copy `.env.example` to `.env`.
2. Replace `POSTGRES_PASSWORD` and `TRACE_APP_PASSWORD`, then update `MIGRATION_DATABASE_URL` and `DATABASE_URL`. Set `RABBITMQ_PASSWORD`. The example derives `AUTH_RABBITMQ_URL` from the RabbitMQ credentials, so use URL-safe values.
3. Generate a different 32-byte base64url value for each required `AUTH_*_KEY`. Set a development-only value for `VAULT_DEV_ROOT_TOKEN_ID`.
4. Add the GitHub and Google client credentials when you want to test OAuth.
5. Start the stack and wait for each health check:

   ```bash
   docker compose up --build --wait
   ```

6. Open the FastAPI health endpoint at [http://localhost:8000/health](http://localhost:8000/health) and the Mailpit inbox at [http://localhost:8025](http://localhost:8025).

PostgreSQL, Redis, RabbitMQ, Mailpit SMTP, and Vault stay on private Docker networks. The backend and worker connect to them as `postgres`, `redis`, `rabbitmq`, `mailpit`, and `vault`.

Stop the stack cleanly with:

```bash
docker compose down
```

This preserves PostgreSQL and RabbitMQ data. Use `docker compose down -v` only when you want to delete local data.

The backend container runs [start.sh](backend/start.sh) with locked dependencies and without runtime downloads. It is non-root, has a read-only filesystem, cannot gain new privileges, and exposes only the API port on localhost. Service images are pinned to immutable digests; update them deliberately as part of maintenance.

## Authentication security configuration

Phase 3 uses a 60-minute Ed25519-signed JWT access token and a rotating opaque refresh token that expires after seven days. Both are designed to be sent only in HttpOnly cookies; they are never returned in JSON responses or stored in browser storage. Email/password accounts require email verification before they can sign in.

Before starting the backend, generate distinct local values for `AUTH_JWT_PRIVATE_KEY`, `AUTH_TOKEN_HASH_KEY`, `AUTH_CSRF_HMAC_KEY`, `AUTH_AUDIT_HASH_KEY`, and `VAULT_DEV_ROOT_TOKEN_ID` in your untracked `.env` file. The four `AUTH_*_KEY` values must be base64url-encoded 32-byte secrets; the command in `.env.example` produces a suitable value. Startup scripts never generate, replace, or print secrets.

JWT key rotation uses `AUTH_JWT_KID` for the active signing key and `AUTH_JWT_VERIFICATION_KEYS` for the short-lived map of retired key IDs to public keys. Sign only with the active key, retain a retired public key only until every token it signed has expired, then remove it.

Production uses `Secure; SameSite=None` host-only cookies and accepts credentialed CORS requests only from `https://trace.fortunealebiosu.dev` and `https://traceai.vercel.app`. These exact origins are enforced at startup. The browser must send the signed CSRF value in `X-CSRF-Token` for unsafe authenticated requests.

The complete authentication contract—including session rotation, OAuth PKCE, recovery, rate limits, failure responses, and audit retention—is in [docs/authentication.md](docs/authentication.md).

Register GitHub and Google OAuth applications with these exact local callback URLs:

- `http://localhost:8000/auth/oauth/github/callback`
- `http://localhost:8000/auth/oauth/google/callback`

Use authorization-code OAuth with PKCE. Provider access and refresh tokens are stored only when Trace needs to call the provider later; Vault Transit encrypts them with AES-256-GCM and binds them to the credential owner and provider before persistence. The Compose Vault instance is development-only; [docs/vault-transit.md](docs/vault-transit.md) defines the self-hosted-server requirements and HCP migration path.

## Database migrations

After copying `.env.example` to `.env`, apply migrations with:

```bash
./scripts/migrate.sh
```

This waits for PostgreSQL and runs Alembic in a separate migration-only container. FastAPI startup never changes the database schema automatically.

## Test database

The `test` Compose profile uses a separate PostgreSQL service, `postgres-test`, and the `trace_test` database. It has its own volume and credentials, so integration migrations cannot modify the development database.

Set `TEST_POSTGRES_PASSWORD` and `TEST_TRACE_APP_PASSWORD` in `.env`, then run:

```bash
./scripts/migrate-test.sh
```

Use `TEST_DATABASE_URL` for integration tests. It targets `postgres-test:5432/trace_test` inside the Compose network; do not substitute `DATABASE_URL` or `MIGRATION_DATABASE_URL` in test commands.
