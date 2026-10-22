#!/bin/sh
# One-time setup of a fresh Amazon Linux 2023 instance for Gaffer (deploy/DEPLOY_AWS.md).
# Run as root (SSM Run Command runs as root). Safe to run again.
#   sh bootstrap.sh            (from an unpacked source tree: uses deploy/ec2/cloudwatch-agent.json)
# Installs Docker and the CloudWatch agent from the Amazon Linux repos, creates the folders that
# survive container restarts (/opt/gaffer/outputs = event DB, uploads, JSONL logs;
# /opt/gaffer/assets = replay clips, sample clip, model), and starts the CloudWatch agent.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)

dnf install -y -q docker amazon-cloudwatch-agent
systemctl enable --now docker

mkdir -p /opt/gaffer/outputs \
         /opt/gaffer/assets/teamtrack/soccer_top/videos \
         /opt/gaffer/assets/sample_clips \
         /opt/gaffer/assets/models \
         /opt/gaffer/src
chown -R 1000:1000 /opt/gaffer/outputs /opt/gaffer/assets   # the container user (uid 1000)

install -m 644 "$HERE/cloudwatch-agent.json" /opt/gaffer/cloudwatch-agent.json
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
    -a fetch-config -m ec2 -s -c file:/opt/gaffer/cloudwatch-agent.json

echo "bootstrap: docker $(docker --version | cut -d' ' -f3 | tr -d ,) ok;" \
     "cloudwatch agent $(/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status | grep -o '"status": "[a-z]*"' | head -1)"
