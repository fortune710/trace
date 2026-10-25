#!/bin/sh
set -eu

cd /root/trace
docker compose --env-file .env.production -f compose.production.yaml exec -T nginx nginx -s reload
