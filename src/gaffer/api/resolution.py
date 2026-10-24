"""Low-resolution note for a finished upload (A3, 24 Oct).

Pixels per metre come from the confirmed pitch corners and the pitch size in `config.yaml`
(`perception.calibration_loop.pixels_per_metre`, the same figure the calibration tiers use). Below
`api.resolution.low_px_per_m` the result carries one plain line; the analysis is never blocked.
"""

from __future__ import annotations

from typing import Any


def resolution_note(px_per_m: float | None, cfg: dict[str, Any]) -> dict[str, Any]:
    """`{px_per_m, threshold_px_per_m, low, message}`; `low` only strictly below the threshold."""
    threshold = float(cfg["api"]["resolution"]["low_px_per_m"])
    if px_per_m is None:
        return {"px_per_m": None, "threshold_px_per_m": threshold, "low": False, "message": None}
    low = float(px_per_m) < threshold
    message = (f"Lower resolution (about {round(float(px_per_m))} px per metre): Gaffer is tested "
               "mainly on 4K drone video; formations may be read less reliably.") if low else None
    return {"px_per_m": round(float(px_per_m), 1), "threshold_px_per_m": threshold, "low": low,
            "message": message}
