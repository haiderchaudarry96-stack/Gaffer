#!/bin/sh
# Build and (re)start Gaffer on the EC2 instance from a source tarball in S3 (deploy/DEPLOY_AWS.md).
# Run as root (SSM Run Command):
#   sh deploy.sh <bucket> <source key>       e.g. gaffer-demo-123456789012 src/gaffer-ebcdd67.tar.gz
# The tarball is `git archive` of one commit (made on the laptop). The image is built here
# (native arm64 / amd64). The container gets no keys: boto3 and Docker's awslogs driver use the
# instance role. Event DB, uploads and logs live in /opt/gaffer/outputs (EBS) and survive
# `docker rm`, redeploys and reboots; `--restart unless-stopped` brings the app back after a reboot.
set -eu
BUCKET="$1"
KEY="$2"
REGION=ap-southeast-2
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

docker rm -f gaffer >/dev/null 2>&1 || true
docker run -d --name gaffer --restart unless-stopped -p 80:8000 \
    -e GAFFER_ASSETS_BUCKET="$BUCKET" -e GAFFER_LOG_LEVEL=INFO \
    -e AWS_REGION="$REGION" -e AWS_DEFAULT_REGION="$REGION" \
    -v /opt/gaffer/outputs:/app/outputs \
    -v /opt/gaffer/assets/teamtrack:/app/data/teamtrack \
    -v /opt/gaffer/assets/sample_clips:/app/data/sample_clips \
    -v /opt/gaffer/assets/models:/app/models \
    --log-driver awslogs --log-opt awslogs-region="$REGION" \
    --log-opt awslogs-group=/gaffer/app --log-opt awslogs-stream=app \
    gaffer:latest >/dev/null

# the first start downloads ~0.6 GB of assets from S3 before uvicorn listens
for _ in $(seq 1 120); do
    if curl -fsS -o /dev/null http://127.0.0.1/api/health; then
        echo "up: http://127.0.0.1/api/health answered $(( $(date +%s) - t0 )) s after start"
        docker image prune -f >/dev/null
        exit 0
    fi
    sleep 5
done
echo "NOT UP after 10 min; last log lines:"
docker logs --tail 40 gaffer
exit 1
