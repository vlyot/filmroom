"""Possession analysis: from a closed possession to the contract's Possession, reading only what was known at
the frame it closed. Offline analysis of a whole match runs the same function, so live and offline agree."""

from dataclasses import dataclass

from filmroom.contracts.models import Decision, Fact, Possession, StyleConfig
from filmroom.data.catalog import MatchData, match_slug
from filmroom.engine.assemble import mmss
from filmroom.engine.decisions import extract_decisions, possession_outcome
from filmroom.engine.geometry import snapshot
from filmroom.engine.options import Candidate, candidate_options, chosen_option_id
from filmroom.engine.pass_model import EngineModels
from filmroom.engine.possessions import RawPossession, split_match
from filmroom.engine.turning_point import EngineParams, regret
from filmroom.engine.xt import danger_curve
from filmroom.style import verdict


@dataclass(frozen=True)
class PossessionAnalysis:
    possession: Possession
    values: list[
        dict[str, float]
    ]  # option ID -> value, per decision; evaluation ranks alternatives with these
    regret: float  # at the final decision, flagged or not


def possession_id(md: MatchData, start_frame: int) -> str:
    return f"{match_slug(md.info.id)}-{start_frame}"


def _facts(md: MatchData, decision: Decision, candidates: list[Candidate], after: int) -> dict[str, Fact]:
    """The narrative slots, under the same IDs the fixtures use. The alternative named is the most valuable
    pass to a teammate, since the narrative templates speak of a player who was available."""
    chosen = next(o for o in decision.options if o.id == decision.chosen_option_id)
    facts = {
        "tp.player": Fact(value=md.player(decision.pid).name, kind="player"),
        "tp.time": Fact(value=mmss(decision.t_ms), kind="text"),
        "chosen.p_success": Fact(value=chosen.p_success, kind="prob"),
        "chosen.p_success_band": Fact(value=chosen.p_success_band, kind="band"),
        "decisions.after_tp": Fact(value=after, kind="count"),
    }
    passes = [c for c in candidates if c.option.kind == "pass" and c.option.target_pid is not None]
    alternatives = [c for c in passes if c.option.id != chosen.id]
    if alternatives:
        alt = max(alternatives, key=lambda c: c.value).option
        facts |= {
            "alt.player": Fact(value=md.player(alt.target_pid).name, kind="player"),
            "alt.p_success": Fact(value=alt.p_success, kind="prob"),
            "alt.p_success_band": Fact(value=alt.p_success_band, kind="band"),
            "alt.danger_gain": Fact(value=alt.danger_gain, kind="xt"),
        }
    return facts


def analyse_possession(
    md: MatchData,
    poss: RawPossession,
    models: EngineModels,
    styles: list[StyleConfig],
    params: EngineParams,
) -> PossessionAnalysis | None:
    view = md.until(poss.close_frame)
    raws = extract_decisions(view, poss)
    if not raws:
        return None
    candidates = [
        candidate_options(snapshot(view, raw.frame, poss.team), raw, idx, models, view.player(raw.pid).key)
        for idx, raw in enumerate(raws)
    ]
    chosen_ids = [chosen_option_id(raw, idx) for idx, raw in enumerate(raws)]
    values = [{c.option.id: c.value for c in options} for options in candidates]
    outcome, zone = possession_outcome(view, poss, raws)
    final_regret = regret(values[-1], chosen_ids[-1])
    flagged = outcome != "goal" and final_regret >= params.flag_threshold
    tp = len(raws) - 1 if flagged else None
    decisions = [
        Decision(
            idx=idx,
            frame=raw.frame,
            t_ms=view.clock.ms_at(raw.frame),
            pid=raw.pid,
            kind=raw.kind,
            chosen_option_id=chosen_ids[idx],
            options=[c.option for c in candidates[idx]],
            is_turning_point=idx == tp,
        )
        for idx, raw in enumerate(raws)
    ]
    possession = Possession(
        id=possession_id(md, poss.start_frame),
        match_id=match_slug(md.info.id),
        team=poss.team,
        start_ms=view.clock.ms_at(poss.start_frame),
        end_ms=view.clock.ms_at(poss.end_frame),
        outcome=outcome,
        ended_zone=zone,
        flagged=flagged,
        severity=round(min(1.0, final_regret / params.severity_scale), 3) if flagged else 0.0,
        turning_point_idx=tp,
        provenance="engine",
        start_frame=poss.start_frame,
        end_frame=poss.end_frame,
        danger_curve=danger_curve(view, poss),
        decisions=decisions,
        verdicts={s.id: verdict(decisions[tp], s, styles[0]) for s in styles} if tp is not None else {},
        facts=_facts(view, decisions[tp], candidates[tp], len(raws) - 1 - tp) if tp is not None else {},
    )
    return PossessionAnalysis(possession, values, final_regret)


def analyse_match(
    md: MatchData, models: EngineModels, styles: list[StyleConfig], params: EngineParams
) -> list[PossessionAnalysis]:
    analyses = (analyse_possession(md, poss, models, styles, params) for poss in split_match(md))
    return [a for a in analyses if a is not None]
