# Trace NGINX loopback bindings

The production Compose project publishes its NGINX HTTP and HTTPS listeners
only on `127.0.0.1:18080` and `127.0.0.1:18443`. The application continues
to serve its own hostname, ACME challenges, and TLS certificate in the
existing NGINX configuration.

Public ports 80 and 443 must be owned by a separately managed host ingress
before this change is deployed. That ingress must route both protocols for the
Trace API hostname:

| API hostname | HTTP target | HTTPS target |
| --- | --- | --- |
| `traceapi.fortunealebiosu.dev` | `127.0.0.1:18080` | `127.0.0.1:18443` |

The production deployment validates HAProxy's configuration before changing
the stack. It then recreates Trace NGINX with its loopback bindings, validates
the local HTTPS `/health` endpoint returns `200`, and reloads HAProxy. Only
after that handoff does `scripts/deploy/verify-shared-ingress.sh` check the
public HTTPS route and HTTP-to-HTTPS redirect. This lets a deployment repair a
currently unhealthy Trace instance without mistaking Trace's former direct
port bindings for shared-ingress readiness.

## Cutover checks

Before deploying the loopback binding change, ensure `/etc/haproxy/haproxy.cfg`
routes `traceapi.fortunealebiosu.dev` to `127.0.0.1:18080` for HTTP and
`127.0.0.1:18443` for HTTPS. HAProxy must be enabled, but it cannot bind public
ports until Trace NGINX releases them during this deployment. The workflow
validates its configuration before the handoff, then reloads it immediately
after NGINX is recreated.

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

Finally, validate NGINX and reload HAProxy:

```sh
docker compose --env-file .env.production -f compose.production.yaml exec -T nginx nginx -t
systemctl reload haproxy
curl --fail --resolve traceapi.fortunealebiosu.dev:18443:127.0.0.1 \
  https://traceapi.fortunealebiosu.dev:18443/health
```

Then verify the public Trace route. The workflow does not block an attempted
repair because the pre-existing Trace instance is unhealthy; it does fail when
the refreshed instance or public routing fails.
