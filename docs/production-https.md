# Production HTTPS and API routing

`compose.production.yaml` runs NGINX on public ports 80 and 443. It forwards
`https://trace.fortunealebiosu.dev/api/v1/...` to the backend's existing
`/api/v1/...` route without adding or removing a path segment. The backend's
`/auth/...` endpoints also pass through NGINX; `/auth/callback` stays on the
frontend for the OAuth completion page. Other frontend requests are proxied to
`https://traceai.vercel.app` so the existing app remains available on this
hostname after DNS moves to the VPS.

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

2. Confirm that the `trace.fortunealebiosu.dev` DNS A record points to the VPS
   public IPv4 address. If an AAAA record exists, it must also point to an IPv6
   address where this Compose stack is reachable; otherwise remove the stale AAAA
   record. Changing this hostname away from Vercel routes the frontend through
   the NGINX proxy above. Check that `https://traceai.vercel.app` serves the
   intended frontend before making the DNS change.
3. Open inbound TCP 80 and 443 in both the VPS firewall and any cloud security
   group. Check that no host web server or other container already binds these
   ports (`sudo ss -ltnp | grep -E ':(80|443)\\b'`). Resolve any conflict
   before starting the NGINX container.
4. From `/root/trace`, create the ACME challenge directory and start NGINX's
   HTTP bootstrap mode. The first start has no certificate and intentionally
   serves only `/.well-known/acme-challenge/`:

   ```sh
   cd /root/trace
   install -d -m 0755 production-acme
   docker compose --env-file .env.production -f compose.production.yaml up -d --no-deps nginx
   ```

5. Once public DNS and port 80 reach the VPS, request the certificate. Replace
   the example email with your real operations email:

   ```sh
   sudo certbot certonly --webroot \
     --webroot-path /root/trace/production-acme \
     --domain trace.fortunealebiosu.dev \
     --email you@example.com --agree-tos --no-eff-email
   ```

6. Start the production stack. NGINX selects its HTTPS configuration when it
   restarts and sees the certificate. Complete the existing Vault setup before
   expecting the full stack to become healthy:

   ```sh
   docker compose --env-file .env.production -f compose.production.yaml up --build -d --wait
   curl -i https://trace.fortunealebiosu.dev/health
   curl -i https://trace.fortunealebiosu.dev/api/v1/projects
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

The frontend build's `VITE_API_BASE_URL` must be
`https://trace.fortunealebiosu.dev` (the origin only). The frontend already
appends `/api/v1/...` for API requests and `/auth/...` for authentication.
Setting this variable to a URL ending in `/api` would create `/api/api/v1/...`.
Keep the production OAuth redirect URIs on the same host under
`/auth/oauth/{provider}/callback`.
