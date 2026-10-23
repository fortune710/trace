# Backend module architecture

Resource APIs are composed by `core.v1` and exposed only under `/api/v1`.
The feature packages are the public ownership boundaries:

- `projects`, `agents`, `reviews`, `findings`, `remediations`, `artifacts`, and
  `credentials` expose their models, schemas, persistence boundary, service,
  route group, and local utilities.
- `external_repositories` owns OAuth-provisioned provider metadata and has no
  public CRUD router.
- `auth` owns authentication and session behavior; `db` owns SQLAlchemy,
  transactions, and RLS context; `audit` owns audit recording.

During the extraction, the feature route groups select the existing handlers
from `resources` so authorization, RLS transactions, CSRF, rate limiting,
audit emission, and secret-safe response behavior stay unchanged. The
`resources` modules are compatibility implementation details and are not
registered directly by `main.py`.

Dependency direction is one-way: routes call services, services call
repositories and shared infrastructure, repositories call database helpers,
and models do not depend on HTTP layers. Alembic imports
`db.model_registry` so all modular model boundaries remain discoverable from
the shared SQLAlchemy metadata.
