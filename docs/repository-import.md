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
the branch name, current commit SHA, and protection status.

### GitHub project creation

GitHub project creation accepts the provider repository ID and selected branch.
The backend revalidates access and resolves the branch immediately before
persisting the project. The persisted project records the provider ID, owner,
repository name, branch, visibility, import timestamp, and resolved commit SHA.

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

## Branch creation service

`external_repositories.service.RepositoryService.create_branch` is an internal
capability for future remediation and pull-request workflows. It requires an
immutable base commit SHA and creates `refs/heads/{branch_name}` from that exact
revision. It does not expose a public branch-creation route in the current API.
