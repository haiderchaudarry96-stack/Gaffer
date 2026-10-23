# Deploy: one Docker container (API + analysis worker + frontend)

The image runs **one process** (`uvicorn gaffer.api.main:app --workers 1`): the FastAPI API, the
single analysis worker (one analysis at a time) and the built frontend (`web/dist`) at `/`.
OpenCV is `opencv-contrib-python-headless==5.0.0.93` (same version as the laptop, no GUI
libraries). **No AWS keys are ever copied into the image**: on EC2 the IAM instance role is used
(boto3's default credential chain); locally Bedrock is optional.

Built and run (22 Oct): on the laptop (amd64, 411 s from an empty cache, image 1.27 GB, health and
`/app` checked) and on EC2 (x86_64 m7i-flex.large, 53 s, 897 MB; live at http://13.210.196.109/).
The image builds the frontend itself (Node stage, `VITE_API_URL=/`), so `web/dist` no longer has to
exist in the build context. Large files are not in the image: the replay clips, the sample clip
and the model are mounted, or fetched from S3 at start when `GAFFER_ASSETS_BUCKET` is set
(`deploy/start.sh`, `gaffer.aws.assets`).

## Build and run locally (laptop, Docker Desktop)

From the repo root:

```powershell
# the image builds the frontend itself (Node stage) with VITE_API_URL=/ (API on the same server)
docker build -f deploy/Dockerfile -t gaffer:latest .
docker run --rm -p 8000:8000 -v "${PWD}/outputs:/app/outputs" `
  -v "${PWD}/data/teamtrack:/app/data/teamtrack:ro" `
  -v "${PWD}/data/sample_clips:/app/data/sample_clips:ro" --name gaffer gaffer:latest
```

The two read-only mounts give the container the 12 replay clips (Live analysis) and the sample
clip; without them the app still runs, `/api/health` then shows `replay_clips: "unavailable: …"`
and `sample_clip: false`. Set `GAFFER_LOG_LEVEL=INFO` (`-e`) to see the `gaffer.*` log lines.

Then open http://localhost:8000/api/health (and http://localhost:8000/ and /app if the frontend
was built).

Without Docker, the same combined app on the laptop is one command after the build above:
`uvicorn gaffer.api.main:app` (http://localhost:8000/).
`outputs/` is mounted so analyses, alerts (`outputs/alerts.jsonl`) and the daily usage counters
survive a restart. The SQLite event DB defaults to `outputs/api/events.sqlite3` and is controlled
by `api.event_store.path` in `config.yaml`; keep that path inside the mounted durable directory.
If `api.storage.backend: s3` is selected, the event DB still stays on local persistent storage;
S3 stores analysis artifacts and does not replace the SQLite database.

Optional, Bedrock from the laptop container (read-only mount of your own AWS config; the image
itself stays key-free):

```powershell
docker run --rm -p 8000:8000 -v "${PWD}/outputs:/app/outputs" `
  -v "$env:USERPROFILE\.aws:/home/gaffer/.aws:ro" gaffer:latest
```

Optional, the TeamTrack reference clip for exact known-clip calibration (otherwise it is
re-anchored to the upload's first frame, see `docs/API.md`):

```powershell
docker run ... -v "${PWD}/data/teamtrack:/app/data/teamtrack:ro" gaffer:latest
```

Smoke test with a video (any top-down MP4 / MOV up to 6 min):

```powershell
curl.exe -F "video=@C:\path\to\match.mp4" http://localhost:8000/api/analyses
curl.exe -X POST -H "Content-Type: application/json" -d "{\"confirmed\": true}" http://localhost:8000/api/analyses/<id>/pitch
curl.exe http://localhost:8000/api/analyses/<id>
```

## On EC2 (deployed 22 Oct): see [DEPLOY_AWS.md](DEPLOY_AWS.md)

Live at **http://13.210.196.109/** (m7i-flex.large in ap-southeast-2; the Free plan refuses
Graviton types). [DEPLOY_AWS.md](DEPLOY_AWS.md) lists the resources and their ids, the real costs,
what was checked on the live server, how to redeploy after a `git pull`, how to stop the instance
and how to delete everything. Files:

- `deploy/ec2/bootstrap.sh`: one-time instance setup (Docker, CloudWatch agent, `/opt/gaffer`).
- `deploy/ec2/deploy.sh <bucket> <src key>`: build the image on the instance and (re)start the
  container (port 80, `--restart unless-stopped`, awslogs to `/gaffer/app`, EBS volumes).
- `deploy/ec2/cloudwatch-agent.json`: the JSONL logs shipped to CloudWatch.
- `deploy/aws/make_iam_policies.py`: the IAM policies (laptop deploy user, instance role).
- `deploy/aws/ssm_run.py`: run a shell script on the instance through SSM Run Command (no SSH).
- No AWS key is ever on the instance or in the image: boto3 and Docker's awslogs driver use the
  instance role (`/api/health` shows `"credentials": "iam-role"`). IMDSv2 hop limit 2 lets the
  container reach it.
- Limits for a public demo live in `config.yaml` → `api.chat`, `api.bedrock_daily`
  (300 Bedrock calls and $1.00 per UTC day for the whole API by default).
