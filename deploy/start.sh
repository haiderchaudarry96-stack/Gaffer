#!/bin/sh
# Container entry (deploy/Dockerfile). 1) copy missing replay clips / sample clip / model from
# S3 when GAFFER_ASSETS_BUCKET is set (never fails the start); 2) one uvicorn process, one worker.
# The demo seed (samples/w900_1260/demo_events_seed.json) is imported by the app itself into an
# empty event DB on first start.
set -e
python -m gaffer.aws.assets
if [ "${GAFFER_TRUST_PROXY:-0}" = "1" ]; then
    # Behind the Caddy container (deploy/ec2/deploy.sh): the app publishes no host port, so Caddy is
    # the only peer on the docker network; it overwrites X-Forwarded-For / -Proto with what it saw.
    # Needed for the client IP (chat allowance without a cookie) and the Secure flag of the cookie.
    set -- --proxy-headers "--forwarded-allow-ips=*"
else
    # no reverse proxy in front: client IPs are taken from the socket, never from X-Forwarded-For
    set -- --no-proxy-headers
fi
exec uvicorn gaffer.api.main:app --host 0.0.0.0 --port 8000 --workers 1 "$@"
