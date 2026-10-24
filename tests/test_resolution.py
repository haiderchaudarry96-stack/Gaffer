"""A3 (24 Oct): the low-resolution note: below, at and above the configured threshold."""

from __future__ import annotations

from gaffer.api.resolution import resolution_note
from gaffer.config import load_config


def test_below_the_threshold_gives_one_plain_line() -> None:
    cfg = load_config()
    note = resolution_note(9.3, cfg)  # the 720p copy of the demo
    assert note["low"] is True and note["threshold_px_per_m"] == 12.0 and note["px_per_m"] == 9.3
    assert note["message"] == ("Lower resolution (about 9 px per metre): Gaffer is tested mainly "
                               "on 4K drone video; formations may be read less reliably.")


def test_at_the_threshold_and_above_there_is_no_note() -> None:
    cfg = load_config()
    thr = float(cfg["api"]["resolution"]["low_px_per_m"])
    for px in (thr, thr + 0.1, 14.7, 29.4):  # at the threshold, 1080p, 4K
        note = resolution_note(px, cfg)
        assert note["low"] is False and note["message"] is None
    just_below = resolution_note(thr - 0.01, cfg)
    assert just_below["low"] is True


def test_threshold_sits_between_720p_and_1080p() -> None:
    thr = float(load_config()["api"]["resolution"]["low_px_per_m"])
    assert 9.3 < thr < 14.7


def test_unknown_scale_is_not_flagged() -> None:
    note = resolution_note(None, load_config())
    assert note["low"] is False and note["px_per_m"] is None and note["message"] is None
