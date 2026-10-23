# Resource schemas and isolation

The resource graph is owned by `public.users` through a non-null `owner_id`.
Provider token ciphertext remains exclusively in `private.credentials`.

`public.repository_source` is shared by projects and external repository
connections. `external_repositories` is currently constrained to `github`;
projects support both `github` and `local`. A GitHub project stores its
provider repository identifier as text and points to an active
`external_repository_connection_id`. A local project stores only its
`local_path_hash`.

Agents are reusable account-owned configurations. `review_run_agents` is the
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
