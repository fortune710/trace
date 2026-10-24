# Resource schemas and isolation

The resource graph is owned by `public.users` through a non-null `owner_id`.
Provider token ciphertext remains exclusively in `private.credentials`.

`public.repository_source` is shared by projects and external repository
connections. `external_repositories` is currently constrained to `github`;
projects support both `github` and `local`. A GitHub project stores its
provider repository identifier as text and points to an active
`external_repository_connection_id`. A local project stores only its
`local_path_hash`.

Agents are reusable account-owned configurations. `review_agents` is the
assignment table, so one run can use many agents and one agent can participate
in many runs. The composite foreign key on `findings` requires the producing
agent to be assigned to the same run and owner.

All resource tables in this phase use forced PostgreSQL RLS. Application
transactions must call `principal_transaction(engine, user_id)`, which sets
the transaction-local `trace.current_user_id`. Services must still include
the principal owner directly in every resource predicate. Same-owner
composite foreign keys prevent relationship traversal across accounts.

The database trigger rejects new or changed GitHub projects that reference a
revoked external repository connection. Revoked connections remain available
for historical records but cannot be selected for new projects.

Audit events are not stored in PostgreSQL. `audit.store.AppendOnlyAuditStore`
is the adapter boundary for immudb or an equivalent append-only system. The
event contract rejects token, secret, ciphertext, and raw request-body fields.

## Immutable review snapshots

Creating a review captures the source and every selected agent in the same
transaction as the review, assignments, and durable dispatch rows. A review
never reads its source or agent configuration from mutable project or agent
records after it is created. PostgreSQL constraints validate the source kind,
algorithm, and digest combination; triggers reject later source or agent
snapshot changes.

GitHub submissions contain project and agent identifiers only. Immediately
before insertion, the backend resolves the configured branch again and stores
the lower-case 40-character commit SHA as a `git-commit-sha1-v1` snapshot.
The safe source identifier is the provider's external repository ID.

Desktop local submissions contain an opaque desktop source UUID, the literal
`sha256-directory-manifest-v1`, and a lower-case 64-character digest. The
backend compares a domain-separated SHA-256 hash of that UUID with the local
project identity hash. It does not receive or persist filesystem paths,
excluded paths, file names, file contents, tokens, provider settings, or
credentials.

The desktop builds the local digest from a binary manifest. It walks regular
files and directories in normalized lexical relative-path order, writes a
version header, and appends records as a one-byte kind (`D` or `F`), an
eight-byte big-endian UTF-8 path length, the UTF-8 path bytes, and, for files,
the file's SHA-256 bytes. The final manifest SHA-256 is the snapshot revision.
It excludes `.git`, `node_modules`, `bower_components`, `jspm_packages`,
`.venv`, `venv`, `env`, `vendor`, `vendor/bundle`, `.bundle`, `packages`,
`.pub-cache`, `deps`, `Pods`, `Carthage`, and `.terraform` at every depth.
Dependency manifests and lockfiles remain included. Symlinks, special or
unreadable files, non-UTF-8 relative paths, and files that change while being
read cause a path-free capture failure.

`review_agents` stores only safe agent display name, specialization, provider,
model, behavior text and skills, plus `configuration_version`. Agent updates
increment that version atomically. Credentials, credential IDs, secrets, and
raw provider settings are excluded from review snapshots.

`private.review_agent_attempts` defines the future provider-attempt contract:
attempt number, state, provider request ID, retry count, timestamps, and a
sanitized failure code. This submission flow does not invoke providers and
does not create attempt rows. When attempts are implemented, terminal attempt
metadata is retained for 90 days; review and source/agent snapshots remain for
the review lifetime.

`private.review_agent_execution_configs` snapshots the optional credential ID
for a selected agent. It is intentionally private and is never returned in a
review response. The execution worker resolves its credential only in memory,
creates attempt rows, and sends no source text, prompts, outputs, or credential
material to its queue messages or LangSmith traces.
