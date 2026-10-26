# Production HTTPS and API routing

`compose.production.yaml` runs NGINX on public ports 80 and 443. It forwards
`https://traceapi.fortunealebiosu.dev/api/v1/...` to the backend's existing
`/api/v1/...` route without adding or removing a path segment. The backend's
`/auth/...` endpoints also pass through NGINX. The frontend remains on
`https://trace.fortunealebiosu.dev` (or its current Vercel hostname), with no
frontend proxy on the API hostname. Unknown API-host paths return 404.

The backend trusts proxy forwarding headers because its port is published on
the VPS loopback interface only. NGINX replaces client supplied forwarding
headers with the connecting address and HTTPS scheme before proxying a request.

## Before switching traffic

1. Ensure the VPS has Docker Engine with the Compose plugin, and install Certbot
   on the host (the example below is for Ubuntu or Debian):

   ```sh
   sudo apt-get update
   sudo apt-get install -y certbot
   ```

2. In Cloudflare DNS, add an `A` record with name `traceapi` and content set to
   the VPS public IPv4 address. Leave the existing `trace` frontend record as
   it is. If an AAAA record exists for `traceapi`, it must point to a reachable
   IPv6 address on the same VPS; otherwise remove that stale record. Use
   DNS-only initially for the HTTP certificate challenge. If you enable the
   Cloudflare proxy later, select SSL/TLS mode **Full (strict)**.
3. Open inbound TCP 80 and 443 in both the VPS firewall and any cloud security
   group. Check that no host web server or other container already binds these
   ports (`sudo ss -ltnp | grep -E ':(80|443)[[:space:]]'`). Resolve any conflict
   before starting the NGINX container.
4. Create the persistent ACME challenge directory outside the Git checkout and
   start NGINX's HTTP bootstrap mode. The first start has no certificate and
   intentionally serves only `/.well-known/acme-challenge/`:

   ```sh
   sudo install -d -m 0755 /var/lib/trace/acme
   cd /root/trace
   docker compose --env-file .env.production -f compose.production.yaml up -d --no-deps nginx
   ```

5. Once public DNS and port 80 reach the VPS, request the certificate. Replace
   the example email with your real operations email:

   ```sh
   sudo certbot certonly --webroot \
     --webroot-path /var/lib/trace/acme \
     --domain traceapi.fortunealebiosu.dev \
     --email you@example.com --agree-tos --no-eff-email
   ```

6. Start the backend, then restart NGINX so it selects its HTTPS configuration.
   Complete the existing Vault setup before expecting the full stack to become
   healthy:

   ```sh
   docker compose --env-file .env.production -f compose.production.yaml up --build -d --wait backend
   docker compose --env-file .env.production -f compose.production.yaml restart nginx
   docker compose --env-file .env.production -f compose.production.yaml up --build -d --wait
   curl -i https://traceapi.fortunealebiosu.dev/health
   curl -i https://traceapi.fortunealebiosu.dev/api/v1/projects
   ```

   The second request should reach the API and return its normal authentication
   response when called without a session. A 404 here usually means the request
   went to the frontend instead of the backend.

## Renewal

Certbot's webroot authenticator uses the same challenge directory while NGINX
is running, so port 80 must stay reachable. Install the certificate deployment
hook to reload NGINX only after a successful renewal:

```sh
sudo install -m 0755 /root/trace/scripts/reload-production-nginx.sh \
  /etc/letsencrypt/renewal-hooks/deploy/trace-nginx
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
```

If your Certbot installation uses a different scheduled renewal service,
configure that service to run `certbot renew` regularly. After a real renewal,
the hook reloads NGINX so it picks up the new certificate.

After changing any tracked NGINX configuration file, validate and reload the
running service; a bind-mounted file change alone does not reload NGINX:

```sh
docker compose --env-file .env.production -f compose.production.yaml exec -T nginx nginx -t
docker compose --env-file .env.production -f compose.production.yaml exec -T nginx nginx -s reload
```

Set the frontend build's `VITE_API_BASE_URL` to
`https://traceapi.fortunealebiosu.dev` (the origin only), then rebuild/redeploy
the frontend. The frontend already appends `/api/v1/...` for API requests and
`/auth/...` for authentication. Do not append `/api` to this variable.

Keep `AUTH_FRONTEND_URL` and `AUTH_ALLOWED_ORIGINS` pointed at the actual
frontend origin(s), including `https://trace.fortunealebiosu.dev` if used.
Set `AUTH_GITHUB_REDIRECT_URI` and `AUTH_GOOGLE_REDIRECT_URI` to the API host,
under `/auth/oauth/github/callback` and `/auth/oauth/google/callback`
respectively. Update those callback URLs in the GitHub and Google OAuth app
settings as well. The user-facing `/auth/callback` route stays on the frontend.

The API keeps its session cookies host-only. Because the frontend cannot read
an API-host cookie, it obtains the signed CSRF token from `GET /auth/csrf`
before authenticated writes. That endpoint requires an active refresh session,
returns a no-store response, and is readable only from configured CORS origins.
Existing sessions issued on the old API hostname do not migrate to `traceapi`;
users will need to sign in again after the frontend switches its API base URL.
For reliable browser cookies, serve the frontend on the same site (for example,
`trace.fortunealebiosu.dev`) rather than relying on third-party cookies from
`traceai.vercel.app`.
