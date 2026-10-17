# Gaffer API + analysis worker + built frontend, one process (docs/API.md, deploy/README.md).
# Build from the repo root:  docker build -f deploy/Dockerfile -t gaffer:latest .
# No AWS keys are ever copied in: on EC2 the IAM instance role is used (boto3 default chain).
# BASE: Docker Hub's official image by default; on EC2 the AWS mirror avoids Docker Hub limits:
#   --build-arg BASE=public.ecr.aws/docker/library/python:3.12-slim
ARG BASE=python:3.12-slim
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
COPY samples ./samples

# the built frontend, if web/dist exists in the build context (npm run build in web/)
RUN --mount=type=bind,source=.,target=/ctx \
    if [ -f /ctx/web/dist/index.html ]; then mkdir -p web && cp -r /ctx/web/dist web/dist \
        && echo "frontend: web/dist included"; else echo "frontend: web/dist not built, API only"; fi

RUN useradd --create-home --uid 1000 gaffer && mkdir -p outputs && chown -R gaffer:gaffer outputs
USER gaffer

EXPOSE 8000
VOLUME ["/app/outputs"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# ONE process and ONE worker: analyses run one at a time inside this process
CMD ["uvicorn", "gaffer.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
