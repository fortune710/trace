# Repository import contract

Trace exposes owner-scoped repository browsing under `/api/v1/repositories`.
The `source` query parameter is required on every repository route. GitHub is
the only supported source today; future providers must implement the same
provider boundary before being added to the accepted values.

## Routes

### `GET /api/v1/repositories?source=github&page=1&page_size=50`

Returns the authenticated builder's GitHub repositories using provider
pagination. The response contains repository ID, owner login, name, full name,
visibility, private status, default branch, and web URL. Repository IDs are
GitHub's immutable numeric identifiers; names are display metadata only.

### `GET /api/v1/repositories/{repository_identifier}/branches?source=github`

The path identifier is the GitHub numeric repository ID. Trace resolves that ID
to the provider owner/name before requesting branches. Branch responses include
the branch name, current commit SHA, and protection status. `page` and
`page_size` use one-based pagination with a maximum page size of 100.

### GitHub project creation

New GitHub imports require this request shape:

```json
{
  "name": "Trace project",
  "source": "github",
  "repository_id": "12345",
  "branch_name": "main",
  "category": "business",
  "auto_create_pull_requests": false
}
```

The backend derives the active GitHub connection from the authenticated account.
It revalidates repository access, resolves the selected branch immediately before
persistence, and stores the provider ID, owner, repository name, branch,
visibility, import timestamp, and resolved commit SHA atomically. Callers must
not send `external_repository_connection_id` or `current_revision`; the latter
is always server-resolved for a new import. Existing stored projects retain their
nullable legacy metadata fields.

The response includes the persisted `external_repository_id`, repository owner
and name, selected branch, visibility, `imported_at`, and the server-resolved
`current_revision` SHA. It also includes the normal project identity, category,
pull-request setting, and timestamps.

## Authorization and errors

GitHub access tokens are decrypted only through the credential service. They are
never returned to the browser, placed in queue messages, or written to logs.

The API uses these sanitized provider errors:

| Condition | Response code |
| --- | --- |
| No active GitHub connection | `403 github_authorization_required` |
| Inaccessible or missing repository | `404 repository_not_found` |
| Missing branch | `404 branch_not_found` |
| Malformed provider ID, branch name, or commit SHA | `400 invalid_request` |
| Unsupported source | `400 unsupported_source` |
| Existing branch | `409 branch_conflict` |
| Provider rate limit | `429 provider_rate_limited` |
| Provider outage or malformed response | `503 provider_unavailable` |

When GitHub supplies a valid numeric `Retry-After` value for a rate limit, Trace
forwards only that value in the response header. Provider response bodies,
authorization headers, tokens, and raw provider messages are never forwarded.

## Branch creation service

`external_repositories.service.RepositoryService.create_branch` is an internal
capability for future remediation and pull-request workflows. It requires an
immutable base commit SHA and creates `refs/heads/{branch_name}` from that exact
revision. It does not expose a public branch-creation route in the current API.
