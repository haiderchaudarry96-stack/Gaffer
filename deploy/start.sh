#!/bin/sh
# Container entry (deploy/Dockerfile). 1) copy missing replay clips / sample clip / model from
# S3 when GAFFER_ASSETS_BUCKET is set (never fails the start); 2) one uvicorn process, one worker.
# The demo seed (samples/w900_1260/demo_events_seed.json) is imported by the app itself into an
# empty event DB on first start.
set -e
python -m gaffer.aws.assets
# no reverse proxy in front: client IPs are taken from the socket, never from X-Forwarded-For
exec uvicorn gaffer.api.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-proxy-headers
