"""scripts/eval_autodetect.py on generated frames (the real run needs TeamTrack: laptop)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

from gaffer.config import load_config
from gaffer.perception.pitch import HomographyMapper

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_autodetect.py"


def _module():
    spec = importlib.util.spec_from_file_location("eval_autodetect", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look their module up here
    spec.loader.exec_module(mod)
    return mod


def test_synthetic_run_writes_json_text_and_refuses_tilt_and_crop(tmp_path) -> None:
    mod = _module()
    out = tmp_path / "eval_autodetect.json"
    assert mod.main(["--synthetic", "4", "--out", str(out), "--failures",
                     str(tmp_path / "failures")]) == 0
    s = json.loads(out.read_text())
    assert s["frames"] == 4 and s["source"] == "synthetic"
    assert s["outcomes"]["success"] == 4 and s["outcomes"]["false_accept"] == 0
    assert s["corner_error_max_m_accepted"]["max"] < 0.5
    assert s["refusal_checks"]["tilted"]["refused"] and s["refusal_checks"]["cropped"]["refused"]
    cost = s["fallback_cost_vs_31_point"]
    assert cost["noise_0px"]["positions_median_m"]["median"] < 0.01  # perfect clicks
    assert (cost["noise_20px"]["positions_median_m"]["median"]
            > cost["noise_5px"]["positions_median_m"]["median"])  # noisier clicks cost more
    txt = out.with_suffix(".txt").read_text()
    assert "false accepts" in txt and "tilted frame: refused" in txt


def test_a_wrong_accept_is_counted_and_saved(tmp_path) -> None:
    mod = _module()
    cfg = load_config()
    item = next(mod.synthetic_items(1))
    # pretend the truth is 10 m to the side: the (correct) detection now looks wrong
    shift = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    shift[0, 2] = 10.0
    item.gt = HomographyMapper(shift @ item.gt.H)
    row = mod.evaluate_item(item, cfg, 1.0, [5.0], np.random.default_rng(42),
                            tmp_path / "failures")
    assert row["accepted"] and row["outcome"] == "false_accept"
    assert list((tmp_path / "failures").glob("autodetect_synthetic_00_0.jpg"))
