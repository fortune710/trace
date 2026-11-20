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
environment to the VPS or recreates any service. The gate requires an HTTPS
`/health` response and an HTTP request that successfully follows an HTTPS
redirect for each hostname. A failure blocks the deployment; fix the external
ingress, DNS, certificate, or upstream routing and rerun the workflow.

## Cutover checks

Before merging the loopback binding change, confirm that the external ingress
owns public TCP ports 80 and 443, then run the same checks as the workflow
from a network outside the VPS. Both hostnames must complete the HTTP redirect
and return a successful HTTPS `/health` response. Do not remove Trace's public
port bindings until these checks succeed.

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
for both API hostnames is restored.
