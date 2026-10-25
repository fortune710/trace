#!/bin/sh
set -eu

certificate_dir=/etc/letsencrypt/live/traceapi.fortunealebiosu.dev
if [ -s "$certificate_dir/fullchain.pem" ] && [ -s "$certificate_dir/privkey.pem" ]; then
  cp /etc/nginx/trace/https.conf /etc/nginx/conf.d/default.conf
else
  cp /etc/nginx/trace/bootstrap.conf /etc/nginx/conf.d/default.conf
fi

exec nginx -g 'daemon off;'
