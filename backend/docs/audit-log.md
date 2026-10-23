# Immutable audit log

Audit history is stored in the configured immudb database. PostgreSQL only holds
`private.audit_delivery_jobs`, a transient outbox used to retry delivery; it is
not an audit-history source of truth.

The API creates bounded events with `AuditRecorder`. Events are canonical JSON
with a SHA-256 hash, and the worker writes the event plus the owner index in one
immudb transaction. The immudb Python client and its persistent root state are
owned by one worker process. Do not share the state file between worker
processes; give each process its own state directory if horizontal scaling is
added.

The application dependency graph intentionally does not include the immudb SDK:
the backend image installs the pinned `immudb-py==1.5.0` package and its
separately pinned runtime requirements from `requirements-audit.txt`, without
the unused `ecdsa` dependency. `backend/ecdsa` provides only the SDK's server
signature-verification surface using `cryptography`; Trace never uses signing,
key generation, or ECDH operations from that compatibility surface.

Internal callers use `AuditService.list_all(page, page_size)` or
`list_for_user(owner_id, page, page_size)`. Pages are one-based, newest-first,
default to 20 items, and are capped at 100. There is intentionally no count
query or public HTTP audit endpoint.

The audit database user is scoped to the audit database with read/write access;
the bootstrap service uses the immudb administrator only to create the database
and user. Rotate `AUDIT_PASSWORD` through the deployment secret mechanism and
restart the audit worker. Rotate the immudb administrator credential separately
and never place either value in the repository or logs.

The immudb data volume is the canonical backup target. Back up the volume using
immudb's supported backup tooling while the server is running, and restore it
before starting the worker. Preserve each worker's root-state directory or allow
the worker to rebuild it from the verified server state before accepting reads.

Jobs that exceed `AUDIT_MAX_ATTEMPTS` become `dead_letter` with only a generic
failure reason. Recovery consists of correcting the dependency, resetting the
selected dead-letter rows to `pending` through a privileged maintenance
operation, and allowing the worker to redeliver. Payloads and exception text
must not be copied into operational logs or manual tickets.
