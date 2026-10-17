"""API contract: the single source of truth for every object the API, static bundle and web app share.

Exported to contracts/schema.json and contracts/openapi.json; the web app's TypeScript types are generated
from the schema. Bump CONTRACT_VERSION on any change consumers must notice.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "0.4.0"

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
    "counter_press",
    "rest_defence",
]
SliderName = Literal["risk_tolerance", "verticality", "press_trigger", "line_height"]
WithBall = Literal["possession", "direct", "counter"]
WithoutBall = Literal["high_press", "mid_block", "low_block"]
LANGUAGE = r"^[a-z]{2}(-[A-Z]{2})?$"
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
    """Option score = sum(weights[f] * option.factors[f]); linear so any verdict change can be attributed.
    Weights are derived from the sliders by the StyleLens."""

    id: str
    name: str
    with_ball: WithBall
    without_ball: WithoutBall
    sliders: Sliders
    weights: dict[FactorName, float]
    principles: list[StylePrinciple]


class SliderSpec(Contract):
    """What one slider does: weights[f] += gains[f] * (slider - 0.5). Each factor has at most one slider, so a
    flip attributed to a factor names the slider behind it."""

    slider: SliderName
    label: str
    statement: str
    gains: dict[FactorName, float]


class RuleSet(Contract):
    """One side of a style: its slider positions and the principles behind them."""

    axis: Literal["with_ball", "without_ball"]
    id: WithBall | WithoutBall
    name: str
    sliders: dict[SliderName, float]
    principles: list[StylePrinciple]


class StyleLens(Contract):
    """Everything needed to build any style from sliders, as the API does: weights = base + the sum over
    sliders of gains * (slider - 0.5). Presets are rule-set pairs; flip reasons are measured against the
    reference."""

    reference_style_id: str
    base: dict[FactorName, float]
    sliders: list[SliderSpec]
    rule_sets: list[RuleSet]


class Claim(Contract):
    """What a narrative asserts, checked against the engine: `better_option` names the best option under the
    style (`ref` is its option ID), `chosen_fits_style` says the choice was the best one, `turning_point`
    names the decision (`ref` is its index) and `style_principle` a factor on the style's card."""

    type: Literal["better_option", "chosen_fits_style", "turning_point", "style_principle"]
    ref: str


class Narrative(Contract):
    """`template` holds {fact.id} slots and `facts` holds their values for this style and language; the
    client fills the slots from `facts` alone, so no number in a narrative ever comes from the LLM.
    Status: `template` (no generation planned), `pending` (template shown, generation queued), `verified`
    (LLM text that passed the verifier) or `failed` (template shown, generation gave up)."""

    possession_id: str
    style_id: str
    audience: Audience
    language: str = Field(pattern=LANGUAGE)
    template: str
    facts: dict[str, Fact]
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
    source: Literal["fixtures", "engine", "database"]
    llm: bool  # whether narratives are generated and the analyst answers


class ChatTurn(Contract):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class AnalystRequest(Contract):
    question: str = Field(min_length=1, max_length=500)
    history: list[ChatTurn] = Field(default=[], max_length=6)
    match_id: str | None = None
    style_id: str | None = None
    language: str = Field(default="en", pattern=LANGUAGE)


class AnalystReply(Contract):
    """The analyst writes no numbers: it cites possessions, and the UI shows their numbers from the engine.
    Status: `verified`, `fallback` (a canned line with the moments found, after the verifier rejected the
    answer twice) or `offline` (no LLM, or the daily allowance is used up)."""

    text: str
    possession_ids: list[str]
    status: Literal["verified", "fallback", "offline"]
    model: str | None = None


class PackTheme(Contract):
    title: str
    summary: str
    possession_ids: list[str]
    status: Literal["verified", "fallback"]


class PackMoment(Contract):
    rank: int
    summary: PossessionSummary
    verdict: Verdict
    narrative: Narrative


class StyleShift(Contract):
    """How many of the pack's moments another preset judges differently, and the factor behind most of
    those flips."""

    style_id: str
    name: str
    changed: int
    factor: FactorName | None


class SessionPack(Contract):
    match_id: str
    team: Side
    style_id: str
    period: Literal["half", "full"]
    audience: Audience
    language: str = Field(pattern=LANGUAGE)
    themes: list[PackTheme]
    moments: list[PackMoment]
    style_shifts: list[StyleShift]


class BundleManifest(Contract):
    contract_version: str
    generated_at: str
    public: bool
    files: list[str]


def template_slots(template: str) -> set[str]:
    return set(SLOT.findall(template))
