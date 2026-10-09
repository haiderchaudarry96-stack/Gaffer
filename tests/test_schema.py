"""Contract validation: round trips, ordering, off-pitch points, version check."""

from __future__ import annotations

import json

import pytest

from gaffer.schema import (
    Alert,
    ContractError,
    ContractVersionError,
    GroundTruth,
    TacticalTimeline,
    load_match_state,
    load_timeline,
)
from tests.conftest import match_dict, player


def _frames(ts: list[float]) -> list[dict]:
    return [{"t": t, "players": [player(1, "home", 50, 30)], "ball": None, "possession": None}
            for t in ts]


def test_match_state_round_trip(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps(match_dict(_frames([0.0, 0.5, 1.0]))), encoding="utf-8")
    m = load_match_state(path)
    assert len(m.frames) == 3 and m.frames[0].players[0].team == "home"
    path.write_text(m.model_dump_json(), encoding="utf-8")
    assert load_match_state(path) == m


@pytest.mark.parametrize("ts", [[0.0, 2.0, 1.0], [0.0, 1.0, 1.0]])
def test_unsorted_or_duplicate_frames_rejected(tmp_path, ts):
    path = tmp_path / "m.json"
    path.write_text(json.dumps(match_dict(_frames(ts))), encoding="utf-8")
    with pytest.raises(ContractError, match="sorted by t"):
        load_match_state(path)


def test_off_pitch_point_rejected_but_small_overshoot_allowed(tmp_path):
    path = tmp_path / "m.json"
    ok = match_dict([{"t": 0.0, "players": [player(1, "home", -4.0, 70.0)]}])
    path.write_text(json.dumps(ok), encoding="utf-8")
    load_match_state(path)
    bad = match_dict([{"t": 0.0, "players": [player(1, "home", 111.0, 30.0)]}])
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ContractError, match="outside the pitch"):
        load_match_state(path)


def test_wrong_contract_version_gives_clear_error(tmp_path):
    path = tmp_path / "m.json"
    data = match_dict(_frames([0.0]))
    data["contract_version"] = "0.9"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ContractVersionError, match="'0.9'.*'1.0'"):
        load_match_state(path)


def test_missing_and_invalid_files(tmp_path):
    with pytest.raises(ContractError, match="not found"):
        load_match_state(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ContractError, match="not valid JSON"):
        load_match_state(bad)


def test_unknown_enum_rejected(tmp_path):
    path = tmp_path / "m.json"
    data = match_dict([{"t": 0.0, "players": [player(1, "spectator", 50, 30)]}])
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ContractError):
        load_match_state(path)


def test_timeline_round_trip_uses_from_alias(tmp_path):
    tl = {
        "contract_version": "1.0", "match_id": "x", "teams": {"home": "Blue", "away": "Red"},
        "segments": [{"start_s": 0.0, "end_s": 60.0,
                      "home": {"formation": "4-4-2", "confidence": 0.8,
                               "defensive_line_m": None, "compactness_m": None, "width_m": None,
                               "centroid": None, "pressing_index": None},
                      "away": {"formation": "uncertain", "confidence": 0.1},
                      "possession_pct": None,
                      "players_visible_mean": {"home": 7.0, "away": 6.5}}],
        "events": [{"id": "evt_001", "t": 30.0, "type": "shape_change", "team": "home",
                    "from": "4-4-2", "to": "3-5-2", "confidence": 0.6, "evidence": "x",
                    "status": "candidate", "verification": None}],
        "quality": {"uncertain_fraction": 0.5, "mean_players_visible": 6.7, "warnings": []},
    }
    path = tmp_path / "tl.json"
    path.write_text(json.dumps(tl), encoding="utf-8")
    loaded = load_timeline(path)
    assert loaded.events[0].from_ == "4-4-2"
    assert '"from":"4-4-2"' in loaded.to_json()
    assert TacticalTimeline.model_validate_json(loaded.to_json()) == loaded


def test_alert_and_ground_truth():
    a = Alert(alert_id="alr_001", event_id="evt_001", created_utc="2026-10-10T00:00:00Z",
              match_time_s=362.0, title="t", explanation="e", suggestion="s")
    assert a.status == "pending"
    with pytest.raises(ValueError):
        Alert(**{**a.model_dump(), "status": "maybe"})
    gt = GroundTruth.model_validate({
        "match_id": "m",
        "formations": [{"team": "home", "from_s": 0, "to_s": 100, "formation": "4-3-3"},
                       {"team": "home", "from_s": 100, "to_s": 200, "formation": "4-4-2"}],
        "changes": [{"team": "home", "t": 100, "from": "4-3-3", "to": "4-4-2"}],
    })
    assert gt.formation_at("home", 99.9) == "4-3-3"
    assert gt.formation_at("home", 100.0) == "4-4-2"
    assert gt.formation_at("away", 50.0) is None
