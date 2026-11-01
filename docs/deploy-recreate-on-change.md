# Recreating services when dependencies or environment change

A production deploy must leave every container running the image and environment
that were just built and configured. A container that keeps running an old image
(missing a new Python dependency) or an old environment (missing a new variable)
fails in confusing ways: the backend crashes on import, or a worker silently runs
with a default.

## What the deploy does

`scripts/deploy/recreate-changed-services.py` replaces the plain
`docker compose up --build -d --wait` step of
`.github/workflows/production-deploy.yml`. It runs on the host from the
repository root:

1. Validates the Compose model first. A required variable that is unset fails the
   deploy before anything is touched.
2. Builds the images. Cached layers are reused.
3. Compares the build and configuration with the record of the last successful
   deploy:
   - **Environment variables:** added, removed or changed names.
   - **Dependency files:** `backend/uv.lock`, `backend/pyproject.toml` and
     `backend/Dockerfile`.
   - **Service configuration:** any service whose resolved Compose definition
     changed.
   - **Images:** whether a service's image ID changed after the build.
4. Inspects the running containers and flags any that run an image other than the
   one just built, or that lack or differ on a configured environment variable.
   This works even when there is no earlier record.
5. Force-recreates the affected services, then brings up the whole stack.
6. Verifies that nothing is stale. If a service still is, the deploy fails and the
   record is not updated, so the next run re-checks everything.

The log names variables and files only. Values are never printed. The record at
`/var/lib/trace/deploy-state/snapshot.json` holds salted hashes, is mode `0600`
and lives in a `0700` directory.

On the first run there is no record, so the script deploys normally, recreates
any container that already drifted, and records a baseline. To reset the record,
delete the state directory.

## Preview and local use

`--dry-run` prints the plan and changes nothing:

```bash
python3 scripts/deploy/recreate-changed-services.py \
  --env-file .env -f compose.yaml --state-dir .deploy-state --dry-run
```

The same command without `--dry-run` also works for local development. A local
backend container built before a dependency was added is rebuilt and recreated
instead of crash-looping.

## Adding an environment variable

A variable used in `compose.production.yaml` reaches a container only if it is
wired through three places. The `deploy-config` merge check fails if any is
missing:

1. Add the name to `REQUIRED` or `OPTIONAL` in
   `.github/scripts/render-production-env.py` (or to `FIXED` for a constant).
2. Add `NAME: ${{ secrets.NAME }}` to the "Prepare production environment" step
   of `production-deploy.yml` and `production-migrations.yml`.
3. Create the GitHub Actions secret.

A variable that is deliberately left to its Compose default goes in
`EXTERNAL_VARIABLES` in `.github/scripts/check-production-env-wiring.py`, with a
reason. The next deploy then reports the new variable by name and recreates the
services that use it.

## Tests

```bash
python3 .github/scripts/check-production-env-wiring.py
python3 -m unittest discover -s scripts/deploy/tests -v
```
