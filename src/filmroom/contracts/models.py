"""API contract: the single source of truth for every object the API, static bundle and web app share.

Exported to contracts/schema.json and contracts/openapi.json; the web app's TypeScript types are generated
from the schema. Bump CONTRACT_VERSION on any change consumers must notice.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "0.1.0"

Side = Literal[0, 1]
Band = Literal["low", "medium", "high"]
Audience = Literal["coach", "player", "fan"]
ActionKind = Literal["pass", "shot", "carry"]
FactorName = Literal[
    "p_success",
    "danger_gain",
    "progression",
    "receiver_space",
    "lane_openness",
    "switch_of_play",
]
SLOT = re.compile(r"\{([a-z0-9_.]+)\}")


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlayerRef(Contract):
    pid: int
    key: str
    name: str
    shirt: int
    team: Side
    role: Literal["GK", "OUT"]


class Team(Contract):
    side: Side
    key: str
    name: str
    attacks_towards_x: float


class MatchSummary(Contract):
    id: str
    title: str
    mode: str
    duration_ms: int
    has_events: bool
    teams: tuple[Team, Team]


class Match(MatchSummary):
    players: list[PlayerRef]


class PositionsChunk(Contract):
    """Samples at a fixed rate. Each row is [x, y] per entity in `pids` order (ball first), flattened."""

    possession_id: str
    t0_ms: int
    hz: int
    pids: list[int]
    xy: list[list[float | None]]


class Option(Contract):
    id: str
    kind: ActionKind
    target_pid: int | None
    target_xy: tuple[float, float] | None
    p_success: float = Field(ge=0, le=1)
    p_success_band: Band
    danger_gain: float
    factors: dict[FactorName, float]


class Decision(Contract):
    idx: int
    frame: int
    t_ms: int
    pid: int
    kind: ActionKind
    chosen_option_id: str
    options: list[Option]
    is_turning_point: bool


class FlipReason(Contract):
    vs_style_id: str
    factor: FactorName
    contribution: float


class Verdict(Contract):
    style_id: str
    decision_idx: int
    best_option_id: str
    chosen_option_id: str
    better_available: bool
    margin: float
    flip_reason: FlipReason | None = None


class DangerPoint(Contract):
    t_ms: int
    xt: float


class Fact(Contract):
    value: float | str
    kind: Literal["prob", "band", "metres", "xt", "count", "player", "text"]
    unit: str | None = None


class PossessionSummary(Contract):
    id: str
    match_id: str
    team: Side
    start_ms: int
    end_ms: int
    outcome: Literal["shot", "goal", "lost_tackle", "lost_pass", "out", "stoppage"]
    ended_zone: Literal["own", "mid", "final"]
    flagged: bool
    severity: float = Field(ge=0, le=1)
    turning_point_idx: int | None
    provenance: Literal["engine", "fixture"]


class Possession(PossessionSummary):
    start_frame: int
    end_frame: int
    danger_curve: list[DangerPoint]
    decisions: list[Decision]
    verdicts: dict[str, Verdict]
    facts: dict[str, Fact]


class Sliders(Contract):
    risk_tolerance: float = Field(ge=0, le=1)
    verticality: float = Field(ge=0, le=1)
    press_trigger: float = Field(ge=0, le=1)
    line_height: float = Field(ge=0, le=1)


class StylePrinciple(Contract):
    text: str
    factor: FactorName
    source: str


class StyleConfig(Contract):
    """Option score = sum(weights[f] * option.factors[f]); linear so any verdict change can be attributed."""

    id: str
    name: str
    with_ball: Literal["possession", "direct", "counter"]
    without_ball: Literal["high_press", "mid_block", "low_block"]
    sliders: Sliders
    weights: dict[FactorName, float]
    principles: list[StylePrinciple]


class Claim(Contract):
    type: Literal["better_option", "turning_point", "player_skill", "style_principle"]
    ref: str


class Narrative(Contract):
    """`template` holds {fact.id} slots; the client fills them from Possession.facts, so no number in a
    narrative ever comes from the LLM."""

    possession_id: str
    style_id: str
    audience: Audience
    language: str = Field(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    template: str
    claims: list[Claim]
    status: Literal["template", "pending", "verified", "failed"]
    model: str | None = None


class OverlayEvent(Contract):
    t_ms: int
    possession_id: str
    moment_type: Literal["turning_point", "shot", "goal"]
    chosen_option_id: str
    best_option_id: str
    captions: dict[str, str]


class Health(Contract):
    status: Literal["ok"]
    contract_version: str
    source: Literal["fixtures", "database"]


class BundleManifest(Contract):
    contract_version: str
    generated_at: str
    public: bool
    files: list[str]


def template_slots(template: str) -> set[str]:
    return set(SLOT.findall(template))
