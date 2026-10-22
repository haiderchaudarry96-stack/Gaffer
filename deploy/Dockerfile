# Gaffer API + analysis worker + built frontend, one process (docs/API.md, deploy/README.md).
# Build from the repo root:  docker build -f deploy/Dockerfile -t gaffer:latest .
# No AWS keys are ever copied in: on EC2 the IAM instance role is used (boto3 default chain).
# BASE / NODE_BASE: Docker Hub's official images by default; on EC2 the AWS mirror avoids Docker
# Hub limits (deploy/ec2/deploy.sh passes these):
#   --build-arg BASE=public.ecr.aws/docker/library/python:3.12-slim
#   --build-arg NODE_BASE=public.ecr.aws/docker/library/node:24-slim
# Works on amd64 and arm64 (Graviton): every pinned wheel exists for both.
ARG BASE=python:3.12-slim
ARG NODE_BASE=node:24-slim

# ---------------------------------------------------------------- 1. frontend (web/dist)
# VITE_API_URL=/ : the API is on this same server, so the site works on any host name.
FROM ${NODE_BASE} AS web
WORKDIR /src
COPY samples ./samples
COPY web/package.json web/package-lock.json ./web/
RUN cd web && npm ci --no-audit --no-fund
COPY web ./web
RUN cd web && VITE_API_URL=/ npm run build && test -f dist/index.html

# ---------------------------------------------------------------- 2. API + OpenCV
FROM ${BASE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# pinned dependencies; the server uses the headless OpenCV build (same version, no GUI libs)
COPY requirements.lock ./
RUN sed 's/^opencv-contrib-python==/opencv-contrib-python-headless==/' requirements.lock \
        > requirements.server.txt \
    && pip install -r requirements.server.txt \
    && python -c "import cv2; assert cv2.__version__.startswith('5.'), cv2.__version__; print('OpenCV', cv2.__version__)"

# the package (editable: config paths resolve against /app, the repo root)
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-deps -e .

COPY config.yaml ./
COPY data/calibration ./data/calibration
COPY data/clips ./data/clips
COPY samples ./samples
COPY deploy/start.sh ./deploy/start.sh
COPY --from=web /src/web/dist ./web/dist

# large files are NOT in the image: on EC2 deploy/start.sh fetches them from S3 into mounted
# volumes (replay clips, sample clip, model); locally mount them (deploy/README.md)
RUN useradd --create-home --uid 1000 gaffer \
    && mkdir -p outputs data/teamtrack/soccer_top/videos data/sample_clips models \
    && chown -R gaffer:gaffer outputs data/teamtrack data/sample_clips models
USER gaffer

EXPOSE 8000
VOLUME ["/app/outputs"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# fetch assets from S3 (only when GAFFER_ASSETS_BUCKET is set), then ONE uvicorn process and ONE
# worker: analyses run one at a time inside this process
CMD ["sh", "deploy/start.sh"]
