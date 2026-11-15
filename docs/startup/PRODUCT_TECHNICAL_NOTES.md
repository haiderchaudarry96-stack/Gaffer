# Technical notes behind the Gaffer product

The public site describes the review workflow. This document preserves the engineering context removed from its evaluation and infrastructure cards. It does not announce a new analysis capability.

| Component | Current implementation | Detailed evidence |
|---|---|---|
| Detection | Classical OpenCV detection for the drone view; tiled YOLOX-S through `cv2.dnn` for experimental side footage | `docs/TECHNICAL_REPORT.md`, `docs/DATA_NOTES.md` |
| Team labels | Kit-colour clustering through `cv2.kmeans`, with gating and per-track votes | `src/gaffer/perception/team_classifier.py` |
| Pitch mapping | `cv2.findHomography` and perspective transforms; calibrated pitch geometry | `src/gaffer/perception/pitch.py`, `docs/DATA_CONTRACT.md` |
| Drift | Per-frame anchoring with `cv2.findTransformECC`, with feature-based fallback | `src/gaffer/perception/drift.py` |
| Camera check | ORB, affine estimation and cut detection to refuse unsupported camera motion | `docs/AGENT_DESIGN.md` |
| Verification | Deterministic frozen rules; OpenCV can prompt another inspection. Bedrock assists bounded orchestration and checked wording | `docs/AGENT_DESIGN.md`, `docs/AGENT_TRACE_EXAMPLES.md` |
| Evidence | Rendered frames and average-position diagrams; timestamps and stored citations | `docs/TECHNICAL_REPORT.md` |

The earlier public figures were scope-dependent. False-alert counts and formation-window accuracy came from synthetic matches; detection/team results came from TeamTrack drone footage of one match. Those values and their protocols remain in `docs/TECHNICAL_REPORT.md` and `docs/DATA_NOTES.md`; they are not general customer accuracy guarantees.

The selected 15:00-21:00 recorded example was chosen using ground-truth positions. Blue's real 18:50 change was missed by the return-leg rule. The 720p formation result is weaker than 4K in the documented one-clip check. No ball, possession or pressing evidence is available; conditional role advice is a heuristic. The footage restrictions and uncertainty remain visible in the product FAQ and upload guide.

## Operator monitoring

The candidate refinement removes monitoring from the public frontend. Public `/api/health` returns only `{"status":"ok"}`. `/api/runtime` and `/api/internal/health` require container loopback and are blocked at Caddy, including on the legacy HTTP/IP listener. They are excluded from the public OpenAPI schema.

Operators with AWS SSM/IAM access can run this **inside the container** through SSM:

```sh
docker exec gaffer python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/internal/health').read().decode())"
```

CloudWatch logs and metrics remain behind AWS IAM. No monitoring credential or administrator interface is added to the public website. The version observed on 14 November exposed the old detailed endpoints; the protections were approved, deployed and verified on 15 November. See [DEPLOYMENT_LATEST.md](DEPLOYMENT_LATEST.md).

## Browser caching

No service worker is registered by the app. The candidate sends `Cache-Control: no-cache` for the HTML shell and named public files, and a one-year immutable cache policy for Vite's content-hashed assets. A missing asset returns 404 rather than the HTML shell. This lets the browser revalidate entry points while safely reusing unchanged bundles.
