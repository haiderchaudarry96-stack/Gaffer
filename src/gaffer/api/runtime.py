"""Live runtime facts for the landing page's "Live on AWS" card (`GET /api/runtime`, also in
`/api/health`). Real values only; a field that cannot be read is `null` (the page says so).

What is read, and what never is:

- **EC2 instance metadata**, IMDSv2 (token `PUT`, then `GET` with the token; hop limit 2 is set on
  the instance so the container can reach it): instance type, availability zone, region. Nothing
  else is requested, so the instance id, account id, IP addresses and the role credentials are
  never read, let alone returned.
- **Bedrock**: the configured model id and the app's own daily counters (`api/usage.py`): calls
  today and the time of the last call. No prompt, answer or cost text.
- **App**: OpenCV version, rules fingerprint, uptime.

Off AWS the metadata service does not answer; the probe gives up within `imds_total_s` (0.9 s) and
the answer is "not running on AWS".
"""

from __future__ import annotations

import re
import threading
import time
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

IMDS_BASE = "http://169.254.169.254"
SAFE_VALUE = re.compile(r"^[A-Za-z0-9._-]{1,48}$")  # instance type, zone, region look like this
FIELDS = (("instance_type", "instance-type"),
          ("availability_zone", "placement/availability-zone"),
          ("region", "placement/region"))

Opener = Callable[..., Any]
# the metadata service is link-local: never through an HTTP(S)_PROXY from the environment
_DIRECT_OPENER: Opener = urllib.request.build_opener(urllib.request.ProxyHandler({})).open


def read_imds(*, timeout_s: float = 0.4, total_s: float = 0.9, base: str = IMDS_BASE,
              opener: Opener = _DIRECT_OPENER,
              clock: Callable[[], float] = time.monotonic) -> dict[str, str | None] | None:
    """Instance type, availability zone and region from IMDSv2, or None when there is no metadata
    service (not EC2, or unreachable). A field that fails alone is None."""
    deadline = clock() + total_s
    try:
        req = urllib.request.Request(f"{base}/latest/api/token", method="PUT",
                                     headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
        with opener(req, timeout=min(timeout_s, total_s)) as resp:
            token = resp.read().decode("ascii", "replace").strip()
    except Exception:  # no route, refused, timeout, blocked in tests: simply not on EC2
        return None
    if not token:
        return None
    out: dict[str, str | None] = {}
    for key, path in FIELDS:
        left = deadline - clock()
        if left <= 0.02:
            out[key] = None
            continue
        try:
            req = urllib.request.Request(f"{base}/latest/meta-data/{path}",
                                         headers={"X-aws-ec2-metadata-token": token})
            with opener(req, timeout=min(timeout_s, left)) as resp:
                value = resp.read().decode("ascii", "replace").strip()
            out[key] = value if SAFE_VALUE.match(value) else None
        except Exception:
            out[key] = None
    return out


class Runtime:
    """Assembles the snapshot. The metadata answer is cached (long when positive, short when
    negative) so the endpoint is cheap and a laptop pays the probe once per half minute at most."""

    def __init__(self, cfg: dict[str, Any], usage: Any, *, bedrock_configured: bool,
                 opencv_version: str, fingerprint: str, storage_backend: str = "local",
                 imds: Callable[[], dict[str, str | None] | None] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        r = cfg["api"].get("runtime", {})
        self.cfg, self.usage, self.clock = cfg, usage, clock
        self.bedrock_configured = bedrock_configured
        self.opencv_version, self.fingerprint = opencv_version, fingerprint
        self.storage_backend = storage_backend
        self.hit_ttl = float(r.get("imds_cache_s", 3600))
        self.miss_ttl = float(r.get("imds_miss_cache_s", 30))
        self.labels: dict[str, str] = dict(r.get("model_labels") or {})
        timeout, total = float(r.get("imds_timeout_s", 0.4)), float(r.get("imds_total_s", 0.9))
        self._imds = imds or (lambda: read_imds(timeout_s=timeout, total_s=total))
        self.started = clock()
        self._lock = threading.Lock()
        self._cached: tuple[float, dict[str, str | None] | None] | None = None

    def _metadata(self) -> dict[str, str | None] | None:
        with self._lock:
            now = self.clock()
            if self._cached is not None:
                at, value = self._cached
                if now - at < (self.hit_ttl if value is not None else self.miss_ttl):
                    return value
            value = self._imds()
            self._cached = (self.clock(), value)
            return value

    def snapshot(self) -> dict[str, Any]:
        meta = self._metadata()
        if meta is None:
            aws: dict[str, Any] = {"running_on_aws": False, "platform": None,
                                   "instance_type": None, "availability_zone": None,
                                   "region": None, "message": "not running on AWS"}
        else:
            aws = {"running_on_aws": True, "platform": "Amazon EC2", "message": None,
                   "instance_type": meta.get("instance_type"),
                   "availability_zone": meta.get("availability_zone"),
                   "region": meta.get("region")}
        model_id = self.cfg["bedrock"]["model_id"]
        used = self.usage.snapshot() if self.usage is not None else {}
        bedrock = {"configured": self.bedrock_configured,
                   "model_id": model_id, "model_label": self.labels.get(model_id, model_id),
                   "region": self.cfg["aws"]["region"],
                   "calls_today": used.get("bedrock_calls"),
                   "calls_cap_today": used.get("bedrock_calls_cap"),
                   "last_call_utc": used.get("last_call_utc")}
        return {"checked_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "aws": aws, "bedrock": bedrock,
                "app": {"opencv_version": self.opencv_version,
                        "rules_fingerprint": self.fingerprint,
                        "uptime_s": int(self.clock() - self.started),
                        "storage": self.storage_backend}}
