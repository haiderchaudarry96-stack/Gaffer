#!/bin/sh
# Build and (re)start Gaffer on the EC2 instance from a source tarball in S3 (deploy/DEPLOY_AWS.md).
# Run as root (SSM Run Command):
#   sh deploy.sh <bucket> <source key> [plain]   e.g. gaffer-demo-123456789012 src/gaffer-ebcdd67.tar.gz
# Default: two containers on the docker network "gaffer-net": "gaffer" (no host port) and "caddy"
# (80 + 443, Let's Encrypt for gaffer-tactics.duckdns.org, plain http for every other host name, see
# deploy/ec2/Caddyfile). `plain` = the 22 Oct setup (no Caddy, "gaffer" publishes port 80): the
# roll-back when HTTPS misbehaves.
# The tarball is `git archive` of one commit (made on the laptop). The image is built here
# (native arm64 / amd64). The container gets no keys: boto3 and Docker's awslogs driver use the
# instance role. Event DB, uploads and logs live in /opt/gaffer/outputs (EBS) and survive
# `docker rm`, redeploys and reboots; Caddy's certificates live in /opt/gaffer/caddy (EBS);
# `--restart unless-stopped` brings both containers back after a reboot.
set -eu
BUCKET="$1"
KEY="$2"
MODE="${3:-https}"
REGION=ap-southeast-2
DOMAIN=gaffer-tactics.duckdns.org
CADDY_IMAGE=public.ecr.aws/docker/library/caddy:2
SRC=/opt/gaffer/src
REV=$(basename "$KEY" .tar.gz | sed 's/^gaffer-//')

t0=$(date +%s)
TMP=$(mktemp -d)
aws s3 cp --region "$REGION" --only-show-errors "s3://$BUCKET/$KEY" "$TMP/src.tar.gz"
rm -rf "$SRC.new" && mkdir -p "$SRC.new"
tar -xzf "$TMP/src.tar.gz" -C "$SRC.new"
rm -rf "$TMP" "$SRC" && mv "$SRC.new" "$SRC"
echo "source: $KEY unpacked in $(( $(date +%s) - t0 )) s"

cd "$SRC"
t1=$(date +%s)
docker build -q -f deploy/Dockerfile \
    --build-arg BASE=public.ecr.aws/docker/library/python:3.12-slim \
    --build-arg NODE_BASE=public.ecr.aws/docker/library/node:24-slim \
    -t gaffer:latest -t "gaffer:$REV" .
echo "build: gaffer:$REV in $(( $(date +%s) - t1 )) s"

docker rm -f gaffer caddy >/dev/null 2>&1 || true
if [ "$MODE" = "plain" ]; then
    NET_ARGS="-p 80:8000"
    TRUST=0
else
    docker network inspect gaffer-net >/dev/null 2>&1 || docker network create gaffer-net >/dev/null
    NET_ARGS="--network gaffer-net"   # no host port: only Caddy can reach the app
    TRUST=1                           # so the app may believe Caddy's X-Forwarded-* headers
fi
# $NET_ARGS is deliberately unquoted (several words)
docker run -d --name gaffer --restart unless-stopped $NET_ARGS \
    -e GAFFER_ASSETS_BUCKET="$BUCKET" -e GAFFER_LOG_LEVEL=INFO -e GAFFER_TRUST_PROXY="$TRUST" \
    -e AWS_REGION="$REGION" -e AWS_DEFAULT_REGION="$REGION" \
    -v /opt/gaffer/outputs:/app/outputs \
    -v /opt/gaffer/assets/teamtrack:/app/data/teamtrack \
    -v /opt/gaffer/assets/sample_clips:/app/data/sample_clips \
    -v /opt/gaffer/assets/models:/app/models \
    --log-driver awslogs --log-opt awslogs-region="$REGION" \
    --log-opt awslogs-group=/gaffer/app --log-opt awslogs-stream=app \
    gaffer:latest >/dev/null

if [ "$MODE" != "plain" ]; then
    # certificates and Caddy's autosave live on the EBS volume (survive redeploys and reboots)
    mkdir -p /opt/gaffer/caddy/data /opt/gaffer/caddy/config
    install -m 644 "$SRC/deploy/ec2/Caddyfile" /opt/gaffer/caddy/Caddyfile
    docker pull -q "$CADDY_IMAGE" >/dev/null
    docker run -d --name caddy --restart unless-stopped --network gaffer-net \
        -p 80:80 -p 443:443 \
        -v /opt/gaffer/caddy/Caddyfile:/etc/caddy/Caddyfile:ro \
        -v /opt/gaffer/caddy/data:/data -v /opt/gaffer/caddy/config:/config \
        --log-driver awslogs --log-opt awslogs-region="$REGION" \
        --log-opt awslogs-group=/gaffer/app --log-opt awslogs-stream=caddy \
        "$CADDY_IMAGE" >/dev/null
fi

# the first start downloads ~0.6 GB of assets from S3 before uvicorn listens; health through the
# front door (Caddy on port 80 in https mode, the app itself in plain mode)
UP=0
for _ in $(seq 1 120); do
    if curl -fsS -o /dev/null http://127.0.0.1/api/health; then
        echo "up: http://127.0.0.1/api/health answered $(( $(date +%s) - t0 )) s after start"
        UP=1
        break
    fi
    sleep 5
done
if [ "$UP" != 1 ]; then
    echo "NOT UP after 10 min; last log lines:"
    docker logs --tail 40 gaffer
    [ "$MODE" = "plain" ] || docker logs --tail 20 caddy
    exit 1
fi
docker image prune -f >/dev/null

if [ "$MODE" != "plain" ]; then
    # the first start asks Let's Encrypt for a certificate (HTTP-01 on port 80): allow 3 min
    for _ in $(seq 1 36); do
        if curl -fsS -o /dev/null --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/health"; then
            echo "https: https://$DOMAIN/api/health answered $(( $(date +%s) - t0 )) s after start"
            exit 0
        fi
        sleep 5
    done
    echo "HTTPS NOT READY after 3 min (plain http works); caddy log:"
    docker logs --tail 40 caddy
    exit 2
fi
