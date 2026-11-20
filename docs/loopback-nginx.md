# Trace NGINX loopback bindings

The production Compose project publishes its NGINX HTTP and HTTPS listeners
only on `127.0.0.1:18080` and `127.0.0.1:18443`. The application continues
to serve its own hostname, ACME challenges, and TLS certificate in the
existing NGINX configuration.

Public ports 80 and 443 must be owned by a separately managed host ingress
before this change is deployed. That ingress must route both protocols for
both API hostnames:

| API hostname | HTTP target | HTTPS target |
| --- | --- | --- |
| `traceapi.fortunealebiosu.dev` | `127.0.0.1:18080` | `127.0.0.1:18443` |
| `keepsafeapi.fortunealebiosu.dev` | `127.0.0.1:28080` | `127.0.0.1:28443` |

The production deployment workflow runs
`scripts/deploy/verify-shared-ingress.sh` before it writes the production
environment to the VPS or recreates any service. The gate requires the HTTPS
ingress to return an HTTP response and HTTP to return a redirect for each
hostname; it does not require either application's health endpoint to be
healthy. After Trace is recreated, the workflow verifies its local HTTPS
`/health` endpoint returns `200`. This lets a deployment repair a currently
unhealthy Trace instance while still failing the run if the refreshed instance
does not become healthy.

## Cutover checks

Before merging the loopback binding change, confirm that the external ingress
owns public TCP ports 80 and 443, then run the same checks as the workflow
from a network outside the VPS. Both hostnames must complete the HTTP redirect
and return an HTTPS response. Do not remove Trace's public port bindings until
these checks succeed.

## Rollback

If the shared ingress cutover fails, restore Trace's direct NGINX port mappings
in `compose.production.yaml`:

```yaml
ports:
  - "80:8080"
  - "443:8443"
```

First stop or reconfigure the external ingress so it releases ports 80 and
443. Then recreate, rather than reload, NGINX so Docker applies the restored
host-port bindings:

```sh
docker compose --env-file .env.production -f compose.production.yaml \
  up -d --force-recreate nginx
```

Finally, verify NGINX's configuration and the public Trace health endpoint.
The deployment gate intentionally remains blocked until shared ingress routing
for both API hostnames is restored, but does not block a deployment solely
because the existing Trace instance is unhealthy.
