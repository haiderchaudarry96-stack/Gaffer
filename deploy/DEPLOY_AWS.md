# Gaffer on AWS (N6a deployment, 22 Oct 2026)

Public app: **https://gaffer-tactics.duckdns.org/** (desk: `/app`, health: `/api/health`); the old
link **http://13.210.196.109/** keeps working over plain http (see "HTTPS" below).

One EC2 instance in **ap-southeast-2 (Sydney)** runs two Docker containers: **Caddy** (TLS, ports 80
and 443) in front of **gaffer**: the FastAPI API, the single analysis worker (OpenCV 5) and the
built frontend. Bedrock (Nova 2 Lite via the global
inference profile) is called from the container with the **instance role**; no access key exists
on the instance or in the image. S3 holds the large files and the source tarball; CloudWatch holds
the logs and two metrics.

```
laptop ── git archive ──► S3 gaffer-demo-<acct>/src/        (source, per commit)
       ── aws s3 cp   ──► S3 gaffer-demo-<acct>/assets/     (replay clips, sample clip, model)
EC2 m7i-flex.large ── deploy.sh: docker build ─► docker network "gaffer-net"
   ├─ container "caddy"  (:80, :443; Let's Encrypt; certificates in /opt/gaffer/caddy on EBS)
   │        └─ reverse proxy ─► container "gaffer" (:8000 on gaffer-net, no host port)
   ├─ gaffer start: assets from S3 -> /opt/gaffer/assets (EBS), demo seed -> event DB (once)
   ├─ /opt/gaffer/outputs (EBS): events.sqlite3, uploads, alerts.jsonl, llm_calls.jsonl, traces
   ├─ Bedrock Converse via instance role (daily caps in config.yaml api.bedrock_daily)
   └─ CloudWatch /gaffer/app: container stdout (awslogs) + JSONL files (CloudWatch agent)
```

## Resources (all tagged `Project=gaffer`)

| Resource | Id / name | Settings |
|---|---|---|
| EC2 instance | `i-0ed7553a2ab9a1d16` (`Name=gaffer`) | **m7i-flex.large** (2 vCPU Intel, 8 GiB), AL2023 x86_64 `ami-0ddbd63d0e3325a92`, subnet `subnet-090b2cd96603f2658` (2a), IMDSv2 required, hop limit 2, no key pair |
| Root volume | `vol-0bb27f75edf65854d` | 30 GB gp3, encrypted, deleted with the instance |
| Elastic IP | `13.210.196.109` (`eipalloc-047975f2cae632e36`) | attached to the instance |
| Security group | `sg-04e763c223e8e3339` (`gaffer-web`) | inbound TCP 80 and TCP 443 from anywhere (443 added 24 Oct, rule `sgr-044a73b130aed520c`; UDP 443 / HTTP/3 stays closed); no SSH (Session Manager instead) |
| DNS name | `gaffer-tactics.duckdns.org` | DuckDNS (free) A record -> the Elastic IP `13.210.196.109`; the certificate is issued for this name only |
| S3 bucket | `gaffer-demo-221039325928` | private (all 4 public-access blocks), SSE-S3, `assets/` 14 files 593.6 MB + `src/` tarballs |
| Log group | `/gaffer/app` | 14-day retention; streams `app`, `llm_calls`, `analysis_trace`, `agent_trace`, `alerts`, `chat_trace`, `posture_trace` |
| Metric filters | `analyses-completed`, `bedrock-calls` | metrics `Gaffer/AnalysesCompleted` (pattern `"analysis_done"`), `Gaffer/BedrockCalls` (one per `llm_calls.jsonl` record) |
| IAM role | `gaffer-ec2-role` (+ instance profile) | `AmazonSSMManagedInstanceCore` + inline `GafferEc2Access` (Nova 2 Lite / Nova Micro profiles only, the one bucket, the one log group) |
| IAM policy | `GafferDeploy` on user `Gaffer-dev` | laptop deploy rights, scoped to Sydney and `Project=gaffer` resources |
| Budget | `gaffer-budget` (existed before) | see "Budget" below |

Policies: `py deploy\aws\make_iam_policies.py <account id> outputs\aws_iam` writes the three
JSON documents (deploy policy, role policy, trust policy). The role was created in the console by
the account owner, so `Gaffer-dev` can pass it to EC2 but never create or edit roles.

**Why not Graviton:** the account is on the AWS **Free plan**, which only launches Free-plan
eligible types. `t4g.large` was refused on 22 Oct with `InvalidParameterCombination: The specified
instance type is not eligible for Free Tier`. Eligible in Sydney (checked with
`describe-instance-types --filters Name=free-tier-eligible,Values=true`): t3.micro/small,
t4g.micro/small, t8i.micro/small, c7i-flex.large, **m7i-flex.large**. So "resize up to c7g.xlarge
for the demo recording" is not possible on this plan; m7i-flex.large is the largest eligible type.

## Costs (Sydney on-demand prices from the AWS price list, 22 Oct 2026)

| Item | Price | Per day |
|---|---|---|
| m7i-flex.large | $0.1197 / h | $2.87 |
| 30 GB gp3 | $0.096 / GB-month | $0.095 |
| Public IPv4 (Elastic IP) | $0.005 / h, also while stopped | $0.12 |
| S3 (0.62 GB) | $0.025 / GB-month | < $0.001 |
| CloudWatch Logs | $0.67 / GB ingested; 2 custom metrics ≤ $0.30 / month each | ~ $0.01–0.03 |
| Bedrock (Nova 2 Lite) | capped by `api.bedrock_daily`: 300 calls and $1.00 per UTC day | 22 Oct: 51 calls, $0.053 |
| **Running total** | **≈ $0.13 / h** | **≈ $3.10 + Bedrock** |
| **Stopped** (disk + IP only) | | **≈ $0.22** |

22 Oct to 9 Nov running 24/7 ≈ 18 days ≈ **$56** + Bedrock. Free-plan credits on 22 Oct: $139.51.
The Free plan never charges the card, but the **account closes when the credits reach $0**, so
watch the credit balance (Billing → Credits), not only the budget.

Data transfer out: one full replay of the 12 clips downloads ~324 MB per viewer; AWS gives
100 GB/month of data transfer out free.

## Observed on the live server (22 Oct)

| Check | Result |
|---|---|
| Image build on the instance (`deploy.sh`) | 53 s; image 897 MB; assets from S3: 14 files, 593.6 MB in 3.5 s; health 200 64 s after the deploy started |
| `/api/health` from the internet | 200 in 0.57 s; OpenCV `5.0.0`, fingerprint `ca4ff9bbf7b01c6c`, region `ap-southeast-2`, `credentials: iam-role`, 12 replay clips, sample clip present |
| Live analysis replay (`web/scripts/e2e-teamtrack-replay.mjs`, `BASE_URL=http://13.210.196.109`) | PASS: 12 clips, 11 seek boundaries, 11 playback handoffs, 1×/2×/4×, event reveal at 1085 s, no browser errors |
| Sample clip (30 s, 1080p) via `POST /api/analyses/sample` | pitch auto-detected (0.993, line error 0.048 m, 754 ms); OpenCV analysis **12.7 s wall** (0.42 s per video s), 60 frames at 2 fps, 26.9 detections/frame, 0 candidates; 1 Bedrock call (coach report) |
| 6-min 4K upload (the 12 replay clips joined, 360.4 s, 3840×2160) | **1,888 s total (31.5 min)**: detection 464 s (1.29 s per video s; laptop 1.18), teams 12 s, agent 1,412 s (OpenCV re-analysis 1,208 s = the frozen 1,200 s budget). 8 candidates: 1 confirmed, 4 rejected, 3 uncertain; 47 Bedrock calls, $0.049 |
| Chat through Bedrock (instance role) | "When did White change shape…": 200 in 5.4 s, `grounded: true`, 3 Nova calls |
| Instance reboot | container back by itself (`unless-stopped`) 5 s after boot; the approved alert, its 8 events, the demo seed (1 event, not duplicated) and the daily usage counter all kept; assets not downloaded again |
| CloudWatch | all 7 streams arriving (agent_trace only when that file exists); `AnalysesCompleted` = 2, `BedrockCalls` = 51 for 22 Oct, equal to the server's own counter |

## HTTPS (24 Oct): Caddy in front of the app

**What runs.** `deploy/ec2/deploy.sh` starts two containers on the docker network `gaffer-net`:

| Container | Image | Ports | State on the EBS volume |
|---|---|---|---|
| `caddy` | `public.ecr.aws/docker/library/caddy:2` (Apache 2.0) | host **80** and **443** | `/opt/gaffer/caddy/data` (certificates, ACME account), `/opt/gaffer/caddy/config`, `/opt/gaffer/caddy/Caddyfile` (copied from `deploy/ec2/Caddyfile` at every deploy) |
| `gaffer` | built from `deploy/Dockerfile` | none published (8000 on `gaffer-net` only) | `/opt/gaffer/outputs`, `/opt/gaffer/assets` (as before) |

Both use `--restart unless-stopped`; the certificate survives redeploys and reboots because it is
on the volume (Let's Encrypt limits duplicate certificates: do not delete `/opt/gaffer/caddy/data`
without a reason).

**Behaviour** (`deploy/ec2/Caddyfile`, validated with Caddy v2.11.7 and tested locally with the real
Gaffer image behind it):

- `https://gaffer-tactics.duckdns.org/`: Let's Encrypt certificate, obtained automatically at the
  first start (HTTP-01 on port 80, TLS-ALPN-01 on 443) and renewed by Caddy itself.
- `http://gaffer-tactics.duckdns.org/...`: `308` redirect to the same path on https (Caddy does this
  for any name it manages).
- `http://<any other host>`: the bare IP `http://13.210.196.109/` and `127.0.0.1` (the health check
  in `deploy.sh`) are served over plain http, not redirected. There is no HSTS header, so a browser
  that has seen the https site does not refuse plain http (this also keeps the roll-back possible).
- Uploads: no request-body limit in the proxy (the app enforces `api.uploads.max_bytes`, 500 MB; a
  520 MB request passed through the test proxy), `read_body` timeout 30 min, response-header timeout
  15 min, idle 10 min.
- Client address: Caddy overwrites `X-Forwarded-For` / `-Proto` with what it saw (a spoofed header
  from a visitor is replaced). The app trusts them **only** when started with
  `GAFFER_TRUST_PROXY=1` (`deploy/start.sh`: `--proxy-headers --forwarded-allow-ips=*`, safe because
  the app publishes no host port and Caddy is the only peer on `gaffer-net`). That gives the chat
  allowance a real client address when the visitor cookie is missing and makes the cookie `Secure`
  on https. With `plain` the old `--no-proxy-headers` applies.
- Logs: `docker logs caddy` and the CloudWatch stream `/gaffer/app` -> `caddy`.

**Roll back to plain http** (no Caddy, `gaffer` publishes port 80 again, as on 22 Oct). On the
instance, as root (the browser shell or `deploy\aws\ssm_run.py`), with the same source tarball:

```sh
SHA=<sha>; B=gaffer-demo-221039325928
aws s3 cp --region ap-southeast-2 s3://$B/src/gaffer-$SHA.tar.gz /tmp/src.tar.gz
rm -rf /tmp/gb && mkdir /tmp/gb && tar -xzf /tmp/src.tar.gz -C /tmp/gb deploy/ec2
sh /tmp/gb/deploy/ec2/deploy.sh $B src/gaffer-$SHA.tar.gz plain     # ~1 min with the Docker cache
```

The image is reused from the cache; the Caddy certificate stays on the volume for the next try. The
443 rule can stay in the security group (nothing listens there in `plain` mode). To go back to
HTTPS run the same lines without `plain`.

**If the certificate is not issued** (`deploy.sh` exits 2 with "HTTPS NOT READY"; plain http still
works): check that `nslookup gaffer-tactics.duckdns.org` returns `13.210.196.109`, that the security
group has TCP 80 and 443 open, and `docker logs caddy` (Let's Encrypt errors are explicit). The
DuckDNS record is not managed by Caddy: if the Elastic IP ever changes, update it on duckdns.org.

**Cost:** Caddy, Let's Encrypt and DuckDNS are free; the container adds about 40 MB of RAM. The
443 rule is free.

## Redeploy after a `git pull`

The repo is private, so the instance never talks to GitHub: the laptop uploads a tarball of one
**committed** revision (`git archive` ignores uncommitted files).

```powershell
# laptop, repo root, after the change is committed
$sha = git rev-parse --short HEAD
git archive --format=tar.gz -o "$env:TEMP\gaffer-$sha.tar.gz" $sha
aws s3 cp "$env:TEMP\gaffer-$sha.tar.gz" "s3://gaffer-demo-221039325928/src/gaffer-$sha.tar.gz" --region ap-southeast-2
```

Then on the instance, as root. Either the browser shell (EC2 console → instance → **Connect →
Session Manager → Connect**, then `sudo -i`) or from the laptop with
`py deploy\aws\ssm_run.py i-0ed7553a2ab9a1d16 3600 <file with these lines>`:

```sh
SHA=<sha>; B=gaffer-demo-221039325928
aws s3 cp --region ap-southeast-2 s3://$B/src/gaffer-$SHA.tar.gz /tmp/src.tar.gz
rm -rf /tmp/gb && mkdir /tmp/gb && tar -xzf /tmp/src.tar.gz -C /tmp/gb deploy/ec2
sh /tmp/gb/deploy/ec2/deploy.sh $B src/gaffer-$SHA.tar.gz
```

`deploy.sh` unpacks the source, builds the image natively, replaces both containers (`gaffer`, `caddy`) and waits for
`/api/health` through Caddy (prints `up: … answered N s after start`, or the last 40 log lines and exit 1), then for
the HTTPS answer (`https: … answered N s after start`; exit 2 if the certificate is not ready after 3 min). The
event DB, uploads and logs under `/opt/gaffer/outputs` are untouched; assets already on disk are
not downloaded again. Expect ~1 min with the Docker cache, a few minutes without.

New instance from scratch: launch as in the table above, then run
`sh /tmp/gb/deploy/ec2/bootstrap.sh` once (Docker, CloudWatch agent, folders) before `deploy.sh`.

## Second sample clip (24 Oct): files that must reach S3

The upload page offers two samples (`api.sample_clip` = TeamTrack, `api.more_sample_clips` = Zenodo).
Both files were uploaded on 24 Oct (the TeamTrack sample replaced the old 218 MB object with the 32 MB re-encode under the same key, so the container's size check fetches the new file at the next start). The Zenodo one is new (1920x1080, 20.6 MB, made by
`py scripts\make_sample_clip.py --source zenodo`). The container fetches every object under
`assets/` into the same path under `/app` at start, so the key must be the repo-relative path:

```powershell
aws s3 cp data\sample_clips\zenodo_top_view_1080p.mp4 s3://gaffer-demo-221039325928/assets/data/sample_clips/zenodo_top_view_1080p.mp4 --region ap-southeast-2
# the TeamTrack sample, 218 MB -> 32 MB (made with: py scripts\make_sample_clip.py --codec x264 --crf 16)
aws s3 cp data\sample_clips\teamtrack_top_sample_1080p.mp4 s3://gaffer-demo-221039325928/assets/data/sample_clips/teamtrack_top_sample_1080p.mp4 --region ap-southeast-2
aws s3 ls s3://gaffer-demo-221039325928/assets/data/sample_clips/ --region ap-southeast-2 --human-readable
```

Then redeploy the code (the new `/api/samples` endpoints and the low-resolution note are code):
the "Redeploy after a `git pull`" steps above. `deploy.sh` recreates the container and the start
script downloads the new file into `/opt/gaffer/assets/sample_clips`. Check
`curl https://gaffer-tactics.duckdns.org/api/samples` lists both ids.

## Stop to save money, start again

```powershell
aws ec2 stop-instances  --region ap-southeast-2 --instance-ids i-0ed7553a2ab9a1d16
aws ec2 start-instances --region ap-southeast-2 --instance-ids i-0ed7553a2ab9a1d16
```

Stopped: ~$0.22/day (disk + Elastic IP). The address stays `13.210.196.109`; Docker and the
container start by themselves on boot (checked with a reboot, see above). The event DB and every
file under `/opt/gaffer` are on the EBS volume and survive a stop.

Back up the event DB (consistent copy while the app runs):

```sh
docker exec gaffer python -c "import sqlite3; s=sqlite3.connect('/app/outputs/api/events.sqlite3'); d=sqlite3.connect('/app/outputs/api/events.backup.sqlite3'); s.backup(d)"
aws s3 cp /opt/gaffer/outputs/api/events.backup.sqlite3 s3://gaffer-demo-221039325928/backup/events-$(date +%F).sqlite3 --region ap-southeast-2
```

## Logs and metrics

- CloudWatch → Log groups → `/gaffer/app` (14 days). `app` = uvicorn + `gaffer.*` INFO lines
  (`analysis_done id=… wall_s=… video_s=… candidates=… bedrock_calls=…`); the other streams are the
  JSONL files, one record per line. Chat questions are logged as typed by visitors (no names, no
  IPs; visitors are a random cookie id).
- CloudWatch → Metrics → `Gaffer` → `AnalysesCompleted`, `BedrockCalls`; use statistic **Sum**,
  period **1 day**. From the laptop:
  `aws cloudwatch get-metric-statistics --region ap-southeast-2 --namespace Gaffer --metric-name BedrockCalls --start-time <day>T00:00:00Z --end-time <next day>T00:00:00Z --period 86400 --statistics Sum`
- On the instance: `docker logs --tail 50 gaffer`, `docker ps`.

## Budget

`gaffer-budget` was $10/month (alerts: actual > 85 %, actual > 100 %, forecast > 100 %); on 22 Oct
it showed $0.49 actual. At ~$3.10/day the server alone crosses $10 in about 3 days, so the alerts
would fire before judging starts. Recommended (Billing → Budgets → `gaffer-budget` → Edit; the
laptop user can only read it):

- **Budgeted amount: $40 / month** (22–31 Oct ≈ 9.3 days × $3.10 ≈ $29 + October so far + Bedrock
  headroom; 1–9 Nov ≈ $28). Keep it at $40 through judging (27 Oct – 9 Nov).
- **Alerts:** actual > 50 % ($20), actual > 80 % ($32), actual > 100 % ($40), forecast > 100 %.
- If the server stays up after 9 Nov, a full month is ~$93: stop or delete it instead of raising
  the budget.
- Bedrock stays capped in `config.yaml` (`api.bedrock_daily`: 300 calls, $1.00 per UTC day).

## Delete everything (in this order)

```powershell
$R = "ap-southeast-2"
# 0. optional: back up the event DB to S3 first (see above), then download what you want to keep
# 1. instance (also deletes its 30 GB root volume: DeleteOnTermination = true)
aws ec2 terminate-instances --region $R --instance-ids i-0ed7553a2ab9a1d16
aws ec2 wait instance-terminated --region $R --instance-ids i-0ed7553a2ab9a1d16
# 2. Elastic IP (charged while it exists, even unattached)
aws ec2 release-address --region $R --allocation-id eipalloc-047975f2cae632e36
# 3. security group (only after the instance is gone)
aws ec2 delete-security-group --region $R --group-id sg-04e763c223e8e3339
# 4. log group (removes both metric filters; the metrics expire on their own)
aws logs delete-log-group --region $R --log-group-name /gaffer/app
# 5. bucket: empty it, then delete it
aws s3 rm s3://gaffer-demo-221039325928 --recursive --region $R
aws s3api delete-bucket --bucket gaffer-demo-221039325928 --region $R
```

In Git Bash prefix the `logs` command with `MSYS_NO_PATHCONV=1` (it rewrites `/gaffer/app`).
Then in the console (needs the account owner): IAM → Roles → `gaffer-ec2-role` → Delete (removes
its inline policy and instance profile); IAM → Users → `Gaffer-dev` → remove `GafferDeploy`;
IAM → Policies → `GafferDeploy` → Delete. Check EC2 → Volumes and Elastic IPs are empty in
Sydney. Keep or delete `gaffer-budget` as you like (budgets are free).
