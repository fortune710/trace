# Shared VPS ingress

The `ingress` service owns public ports 80 and 443. It forwards HTTP by Host
and HTTPS by TLS SNI to the application NGINX containers on loopback ports.
Each application keeps its own TLS certificate and ACME webroot. The ingress
does not decrypt TLS or share application credentials.

| Hostname | HTTP loopback | HTTPS loopback |
| --- | ---: | ---: |
| `traceapi.fortunealebiosu.dev` | `127.0.0.1:18080` | `127.0.0.1:18443` |
| `keepsafeapi.fortunealebiosu.dev` | `127.0.0.1:28080` | `127.0.0.1:28443` |

Merge this change before the Keepsafe deployment PR. Trace's normal merged-PR
workflow validates the Compose file, moves its NGINX ports to loopback, and
starts the ingress service. Verify both Trace HTTP redirect and HTTPS health
before creating the Keepsafe DNS record. The Keepsafe backend remains
unavailable until its own stack is started.

The VPS must not have another listener on ports 80 or 443. If cutover fails,
restore the previous Compose file and redeploy Trace through its normal
workflow after removing the failed ingress container.
