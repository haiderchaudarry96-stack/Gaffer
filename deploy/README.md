# Deploy: one Docker container (API + analysis worker + frontend)

The image runs **one process** (`uvicorn gaffer.api.main:app --workers 1`): the FastAPI API, the
single analysis worker (one analysis at a time) and the built frontend (`web/dist`) at `/`.
OpenCV is `opencv-contrib-python-headless==5.0.0.93` (same version as the laptop, no GUI
libraries). **No AWS keys are ever copied into the image**: on EC2 the IAM instance role is used
(boto3's default credential chain); locally Bedrock is optional.

Not built yet: the cloud session that wrote this could not pull a base image (Docker Hub rate
limit, AWS mirror blocked by its proxy). The same install and run steps were checked in a clean
Python 3.12 virtualenv with `uvicorn` and `curl`.

## Build and run locally (laptop, Docker Desktop)

From the repo root:

```powershell
# optional: build the frontend first so the image serves it at /
cd web; npm ci; $env:VITE_API_URL="http://localhost:8000"; npm run build; cd ..

docker build -f deploy/Dockerfile -t gaffer:latest .
docker run --rm -p 8000:8000 -v "${PWD}/outputs:/app/outputs" --name gaffer gaffer:latest
```

Then open http://localhost:8000/api/health (and http://localhost:8000/ if the frontend was built).
`outputs/` is mounted so analyses, alerts (`outputs/alerts.jsonl`) and the daily usage counters
survive a restart.

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

## On EC2 (Phase 4, next session: needs the user's OK on cost first)

- Base image: Docker Hub's anonymous pull limit can bite on shared IPs; the AWS mirror avoids it:
  `docker build --build-arg BASE=public.ecr.aws/docker/library/python:3.12-slim -f deploy/Dockerfile -t gaffer:latest .`
- Instance role with least privilege: `bedrock:InvokeModel` on the two inference profiles in
  `config.yaml` (+ the underlying Nova models), `s3:GetObject/PutObject/ListBucket` on the results
  bucket if `api.storage.backend: s3`, CloudWatch Logs `logs:CreateLogStream/PutLogEvents`.
- The configured profile `default` does not exist on EC2: the API then uses the instance role
  automatically (`api/main.py _bedrock_factory`).
- Region `ap-southeast-2`. CPU only: a 6-min 4K drone clip is ~7 min of OpenCV on the laptop CPU;
  measure on the instance before sizing it.
- Limits for a public demo live in `config.yaml` → `api.chat`, `api.bedrock_daily`
  (300 Bedrock calls and $1.00 per UTC day for the whole API by default).
