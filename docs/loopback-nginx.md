# Trace NGINX loopback bindings

The production Compose project publishes its NGINX HTTP and HTTPS listeners
only on `127.0.0.1:18080` and `127.0.0.1:18443`. The application continues
to serve its own hostname, ACME challenges, and TLS certificate in the
existing NGINX configuration.

Public ports 80 and 443 must be owned by a separately managed host ingress
before this change is deployed. Validate its routing and rollback procedure
before merging this PR. The Trace production workflow still deploys through
the normal merged-PR path.
