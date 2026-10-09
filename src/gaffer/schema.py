"""The Gaffer data contract (`docs/DATA_CONTRACT.md`) as pydantic models.

`MatchState` is emitted identically by the synthetic generator, the OpenCV pipeline and the
TeamTrack oracle; `TacticalTimeline` is what the tactics engine emits and the agent reads;
`Alert` is one line of `outputs/alerts.jsonl`; `GroundTruth` is read only by eval scripts.

Every file carries `contract_version`. Loading a file with a different version raises
`ContractVersionError` with a clear message instead of a validation traceback.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CONTRACT_VERSION = "1.0"

#: A point further than this outside the pitch is a bad projection (dropped, not clamped).
OFF_PITCH_TOLERANCE_M = 5.0

Side = Literal["home", "away"]
TeamLabel = Literal["home", "away", "referee", "unknown"]
Role = Literal["outfield", "goalkeeper"]
Possession = Literal["home", "away", "contested", "dead"]
Direction = Literal["left", "right"]
Source = Literal["synthetic", "video", "annotation"]
EventType = Literal["shape_change", "line_drop", "press_trigger"]
EventStatus = Literal["candidate", "confirmed", "rejected", "uncertain"]
Decision = Literal["confirmed", "rejected", "uncertain"]
AlertStatus = Literal["pending", "approved", "rejected"]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class ContractError(ValueError):
    """A contract file is missing, unreadable or invalid."""


class ContractVersionError(ContractError):
    """A contract file carries a `contract_version` this code does not understand."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Versioned(_Model):
    contract_version: str = CONTRACT_VERSION

    @field_validator("contract_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v != CONTRACT_VERSION:
            raise ValueError(f"unsupported contract_version {v!r}, expected {CONTRACT_VERSION!r}")
        return v


# --------------------------------------------------------------------------- MatchState


class Pitch(_Model):
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)


class SourceVideo(_Model):
    uri: str
    native_fps: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class TeamInfo(_Model):
    name: str
    colour: str
    attacking_direction_first_half: Direction


class Teams(_Model):
    home: TeamInfo
    away: TeamInfo


class Period(_Model):
    name: str
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Period:
        if self.end_s <= self.start_s:
            raise ValueError(f"period {self.name!r}: end_s must be after start_s")
        return self


class Player(_Model):
    track_id: int
    team: TeamLabel
    role: Role = "outfield"
    x: float
    y: float
    confidence: Confidence = 1.0
    interpolated: bool = False


class Ball(_Model):
    x: float | None = None
    y: float | None = None
    visible: bool = False


class FrameQuality(_Model):
    players_detected: int = Field(ge=0)
    homography_ok: bool = True
    reprojection_error_m: float | None = None
    camera_cut: bool = False


class Frame(_Model):
    t: float = Field(ge=0)
    players: list[Player] = Field(default_factory=list)
    ball: Ball | None = None
    possession: Possession | None = None
    quality: FrameQuality | None = None


class Meta(_Model):
    generator: str
    opencv_version: str | None = None
    created_utc: str
    notes: str = ""


class MatchState(_Versioned):
    match_id: str
    source: Source
    fps: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    pitch: Pitch
    source_video: SourceVideo | None = None
    teams: Teams
    periods: list[Period] = Field(min_length=1)
    frames: list[Frame]
    meta: Meta

    @model_validator(mode="after")
    def _check_frames(self) -> MatchState:
        prev = -1.0
        for f in self.frames:
            if f.t <= prev:
                raise ValueError(f"frames must be sorted by t with no duplicates (t={f.t})")
            prev = f.t
        tol = OFF_PITCH_TOLERANCE_M
        L, W = self.pitch.length_m, self.pitch.width_m
        for f in self.frames:
            for p in f.players:
                if not (-tol <= p.x <= L + tol and -tol <= p.y <= W + tol):
                    raise ValueError(
                        f"player track {p.track_id} at t={f.t} is more than {tol} m outside "
                        f"the pitch ({p.x:.1f}, {p.y:.1f}); producers must drop such points"
                    )
        return self

    def period_at(self, t: float) -> int:
        """Index of the period containing `t` (the last period that started at or before t)."""
        idx = 0
        for i, p in enumerate(self.periods):
            if t >= p.start_s:
                idx = i
        return idx


# --------------------------------------------------------------------------- TacticalTimeline


class Point(_Model):
    x: float
    y: float


class TeamSegmentStats(_Model):
    formation: str  # a template name or "uncertain"
    confidence: Confidence
    defensive_line_m: float | None = None
    compactness_m: float | None = None
    width_m: float | None = None
    centroid: Point | None = None
    pressing_index: Confidence | None = None


class Segment(_Model):
    start_s: float
    end_s: float
    home: TeamSegmentStats
    away: TeamSegmentStats
    possession_pct: dict[Side, int] | None = None
    players_visible_mean: dict[Side, float]


class Verification(_Model):
    decided_by: str
    decision: Decision
    reason: str
    tool_calls: list[str] = Field(default_factory=list)
    evidence_image: str | None = None
    trace_id: str | None = None


class Event(_Model):
    id: str
    t: float
    type: EventType
    team: Side
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    confidence: Confidence
    evidence: str
    status: EventStatus = "candidate"
    verification: Verification | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TimelineQuality(_Model):
    uncertain_fraction: Confidence
    mean_players_visible: float
    warnings: list[str] = Field(default_factory=list)


class TacticalTimeline(_Versioned):
    match_id: str
    teams: dict[Side, str]
    segments: list[Segment]
    events: list[Event]
    quality: TimelineQuality

    def to_json(self) -> str:
        """Compact JSON (the timeline must stay under ~8 KB for a full match)."""
        return self.model_dump_json(by_alias=True, exclude_none=False)


# --------------------------------------------------------------------------- Alerts


class Alert(_Model):
    alert_id: str
    event_id: str
    created_utc: str
    match_time_s: float
    title: str
    explanation: str
    suggestion: str
    evidence_image: str | None = None
    status: AlertStatus = "pending"
    decided_utc: str | None = None
    coach_note: str | None = None


# --------------------------------------------------------------------------- Ground truth


class GTFormation(_Model):
    team: Side
    formation: str
    from_s: float | None = None
    to_s: float | None = None
    t: float | None = None  # point label (real clips)


class GTChange(_Model):
    team: Side
    t: float
    from_: str = Field(alias="from")
    to: str

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GTNoiseEvent(_Model):
    """A moment that looks like a shape change but is not (synthetic only)."""

    kind: Literal["set_piece", "counter_attack", "flicker"]
    team: Side
    start_s: float
    end_s: float


class GTVisibility(_Model):
    """A stretch where the camera shows only part of the pitch (synthetic only)."""

    mode: Literal["broadcast"]
    start_s: float
    end_s: float


class GroundTruth(_Model):
    match_id: str
    formations: list[GTFormation]
    changes: list[GTChange]
    noise_events: list[GTNoiseEvent] = Field(default_factory=list)
    visibility: list[GTVisibility] = Field(default_factory=list)

    def formation_at(self, team: Side, t: float) -> str | None:
        """True formation of `team` at time `t` (interval labels only)."""
        for f in self.formations:
            if f.team == team and f.from_s is not None and f.to_s is not None:
                if f.from_s <= t < f.to_s:
                    return f.formation
        return None


# --------------------------------------------------------------------------- loading


def _read_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise ContractError(f"File not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"{p} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{p} must contain a JSON object")
    return data


def _validate[M: BaseModel](model: type[M], data: dict[str, Any], where: str) -> M:
    version = data.get("contract_version")
    if issubclass(model, _Versioned) and version != CONTRACT_VERSION:
        raise ContractVersionError(
            f"{where}: contract_version is {version!r} but this code reads {CONTRACT_VERSION!r}. "
            "Regenerate the file or migrate it (see docs/DATA_CONTRACT.md, Versioning)."
        )
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ContractError(f"{where} is not a valid {model.__name__}:\n{exc}") from exc


def load_match_state(path: str | os.PathLike[str]) -> MatchState:
    """Load and validate a `match_state.json`. Raises `ContractError` on any problem."""
    return _validate(MatchState, _read_json(path), str(path))


def load_timeline(path: str | os.PathLike[str]) -> TacticalTimeline:
    """Load and validate a `tactical_timeline.json`. Raises `ContractError` on any problem."""
    return _validate(TacticalTimeline, _read_json(path), str(path))


def load_ground_truth(path: str | os.PathLike[str]) -> GroundTruth:
    """Load and validate a ground-truth file (eval scripts only)."""
    return _validate(GroundTruth, _read_json(path), str(path))


def parse_match_state(data: dict[str, Any], where: str = "match_state") -> MatchState:
    """Validate an in-memory dict as a `MatchState` (same errors as `load_match_state`)."""
    return _validate(MatchState, data, where)
