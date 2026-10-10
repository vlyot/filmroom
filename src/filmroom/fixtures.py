"""Fixture builder: contract-valid possessions for Phases 3 and 4 to build against before the engine exists.

Positions, decisions and players come from the real data; option values come from the hand-set spec
(fixtures/fixture_spec.json), and verdicts are computed from the style presets with the same linear score the
web app uses. Output holds SoccER-derived positions, so it is written to gitignored folders only.
"""

from pathlib import Path

import numpy as np

from filmroom.api.store import FixturePossession
from filmroom.contracts.models import (
    ActionKind,
    Band,
    Claim,
    Contract,
    DangerPoint,
    Decision,
    Fact,
    FactorName,
    Match,
    Narrative,
    Option,
    PlayerRef,
    PositionsChunk,
    Possession,
    StyleConfig,
    Team,
    template_slots,
)
from filmroom.data.catalog import MatchData, match_slug
from filmroom.data.positions import BALL_PID, downsample
from filmroom.data.textlog import PassComplete, PassStart, Shot
from filmroom.eval.labels import LabelRecord
from filmroom.eval.scoring import DecisionPoint, label_decision_idx
from filmroom.style import verdict

DECISION_SLACK_FRAMES = 50  # labelled windows end on the last touch; its pass or shot can start a frame later


class OptionSpec(Contract):
    p_success: float
    danger_gain: float
    factors: dict[FactorName, float]


class PossessionSpec(Contract):
    label_id: str
    outcome: str
    ended_zone: str
    severity: float
    chosen: OptionSpec
    better: OptionSpec
    other: OptionSpec


class FixtureSpec(Contract):
    routine: OptionSpec  # value for decisions that are not the turning point
    narratives: dict[str, str]  # "audience.language" -> template with {fact.id} slots
    possessions: list[PossessionSpec]


def band(p: float) -> Band:
    return "high" if p >= 2 / 3 else "medium" if p >= 1 / 3 else "low"


def _team(pid: int) -> int:
    return 1 if pid > BALL_PID else 0


def _mmss(ms: int) -> str:
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}"


def build_match(md: MatchData) -> Match:
    home, away = md.teams
    return Match(
        id=match_slug(md.info.id),
        title=f"{home.name} v {away.name}",
        mode=md.info.mode,
        duration_ms=int(md.clock.ms[-1]),
        has_events=md.has_events,
        teams=tuple(
            Team(side=t.side, key=t.key, name=t.name, attacks_towards_x=t.attacks_towards_x) for t in md.teams
        ),
        players=[
            PlayerRef(pid=p.pid, key=p.key, name=p.name, shirt=p.shirt, team=p.team, role=p.role)
            for p in md.players
        ],
    )


def decision_points(md: MatchData, start: int, end: int, team: int) -> list[tuple[int, int, ActionKind]]:
    points: dict[int, tuple[int, ActionKind]] = {}
    last = end + DECISION_SLACK_FRAMES
    for e in md.events:
        if isinstance(e, PassStart) and start <= e.frame <= last and _team(e.pid) == team:
            points[e.frame] = (e.pid, "pass")
        elif isinstance(e, Shot) and start <= e.start_frame <= last and _team(e.pid) == team:
            points[e.start_frame] = (e.pid, "shot")
    return [(frame, pid, kind) for frame, (pid, kind) in sorted(points.items())]


def _position(md: MatchData, frame: int, pid: int) -> tuple[float, float]:
    row = min(int(np.searchsorted(md.track.frames, frame)), len(md.track.frames) - 1)
    col = list(md.track.pids).index(pid)
    x, y = md.track.xy[row, col]
    return (round(float(x), 2), round(float(y), 2))


def _option(oid: str, kind: ActionKind, target: int | None, xy, spec: OptionSpec) -> Option:
    return Option(
        id=oid,
        kind=kind,
        target_pid=target,
        target_xy=xy,
        p_success=spec.p_success,
        p_success_band=band(spec.p_success),
        danger_gain=spec.danger_gain,
        factors=spec.factors,
    )


def _nearest_teammate(md: MatchData, frame: int, pid: int, exclude: set[int]) -> int:
    origin = np.asarray(_position(md, frame, pid))
    mates = [p.pid for p in md.players if p.team == _team(pid) and p.pid not in exclude | {pid}]
    return min(mates, key=lambda m: float(np.linalg.norm(np.asarray(_position(md, frame, m)) - origin)))


def build_possession(
    label: LabelRecord,
    md: MatchData,
    spec: PossessionSpec,
    routine: OptionSpec,
    templates: dict[str, str],
    styles: list[StyleConfig],
) -> FixturePossession:
    team = _team(label.tp_pid)
    points = decision_points(md, label.start_frame, label.end_frame, team)
    tp_idx = label_decision_idx(label, [DecisionPoint(f, p) for f, p, _ in points])
    if tp_idx is None:
        raise ValueError(f"{label.id}: no decision within a second of the labelled turning point")
    receivers = {e.start_frame: e.receiver for e in md.events if isinstance(e, PassComplete)}
    goal_xy = (110.0, 36.0) if team == 0 else (0.0, 36.0)

    decisions = []
    for idx, (frame, pid, kind) in enumerate(points):
        receiver = receivers.get(frame)
        chosen_xy = goal_xy if kind == "shot" else _position(md, frame, receiver) if receiver else None
        is_tp = idx == tp_idx
        options = [_option(f"d{idx}.chosen", kind, receiver, chosen_xy, spec.chosen if is_tp else routine)]
        if is_tp:
            other = _nearest_teammate(md, frame, pid, {label.better_pid, receiver})
            options.append(
                _option(
                    f"d{idx}.better",
                    "pass",
                    label.better_pid,
                    _position(md, frame, label.better_pid),
                    spec.better,
                )
            )
            options.append(_option(f"d{idx}.other", "pass", other, _position(md, frame, other), spec.other))
        decisions.append(
            Decision(
                idx=idx,
                frame=frame,
                t_ms=md.clock.ms_at(frame),
                pid=pid,
                kind=kind,
                chosen_option_id=options[0].id,
                options=options,
                is_turning_point=is_tp,
            )
        )

    tp = decisions[tp_idx]
    possession_id = f"{match_slug(md.info.id)}-{label.start_frame}"
    facts = {
        "tp.player": Fact(value=md.player(tp.pid).name, kind="player"),
        "tp.time": Fact(value=_mmss(tp.t_ms), kind="text"),
        "chosen.p_success": Fact(value=spec.chosen.p_success, kind="prob"),
        "chosen.p_success_band": Fact(value=band(spec.chosen.p_success), kind="band"),
        "alt.player": Fact(value=md.player(label.better_pid).name, kind="player"),
        "alt.p_success": Fact(value=spec.better.p_success, kind="prob"),
        "alt.p_success_band": Fact(value=band(spec.better.p_success), kind="band"),
        "alt.danger_gain": Fact(value=spec.better.danger_gain, kind="xt"),
        "decisions.after_tp": Fact(value=len(decisions) - 1 - tp_idx, kind="count"),
    }
    for key, template in templates.items():
        if missing := template_slots(template) - set(facts):
            raise ValueError(f"{label.id} narrative {key} uses unknown facts: {sorted(missing)}")

    window = md.track.window(label.start_frame, label.end_frame)
    samples = downsample(window, md.clock, hz=10)
    ball = list(samples.pids).index(BALL_PID)
    curve = []
    for row in range(0, len(samples.frames), 5):
        x = float(samples.xy[row, ball, 0])
        progress = x / 110 if team == 0 else 1 - x / 110
        curve.append(
            DangerPoint(t_ms=md.clock.ms_at(int(samples.frames[row])), xt=round(0.02 + 0.3 * progress**3, 4))
        )

    possession = Possession(
        id=possession_id,
        match_id=match_slug(md.info.id),
        team=team,
        start_ms=md.clock.ms_at(label.start_frame),
        end_ms=md.clock.ms_at(label.end_frame),
        outcome=spec.outcome,
        ended_zone=spec.ended_zone,
        flagged=True,
        severity=spec.severity,
        turning_point_idx=tp_idx,
        provenance="fixture",
        start_frame=label.start_frame,
        end_frame=label.end_frame,
        danger_curve=curve,
        decisions=decisions,
        verdicts={s.id: verdict(tp, s, styles[0]) for s in styles},
        facts=facts,
    )
    positions = PositionsChunk(
        possession_id=possession_id,
        t0_ms=md.clock.ms_at(int(samples.frames[0])),
        hz=10,
        pids=[int(p) for p in samples.pids],
        xy=[[None if np.isnan(v) else round(float(v), 2) for v in row.ravel()] for row in samples.xy],
    )
    narratives = [
        Narrative(
            possession_id=possession_id,
            style_id=s.id,
            audience=key.split(".")[0],
            language=key.split(".")[1],
            template=template,
            claims=[Claim(type="better_option", ref=f"d{tp_idx}.better")],
            status="template",
        )  # fmt: skip
        for s in styles
        for key, template in templates.items()
    ]
    return FixturePossession(
        label_id=label.id, possession=possession, positions=positions, narratives=narratives
    )


def write_fixtures(out_dir: Path, matches: list[Match], fixtures: list[FixturePossession]) -> None:
    for sub in ("matches", "possessions"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    for m in matches:
        (out_dir / "matches" / f"{m.id}.json").write_text(m.model_dump_json(indent=1), encoding="utf-8")
    for f in fixtures:
        path = out_dir / "possessions" / f"{f.possession.id}.json"
        path.write_text(f.model_dump_json(), encoding="utf-8")
