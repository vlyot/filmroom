"""The engine tools the agents call over MCP. Each returns a compact, named view of engine output; the
docstrings are what the model reads as tool descriptions. Every number here comes from the engine."""

from pydantic import BaseModel

from filmroom.agents.facts import action_phrase, player_name
from filmroom.api.store import Store
from filmroom.contracts.models import (
    Decision,
    FactorName,
    Match,
    Option,
    Possession,
    SliderName,
    Sliders,
    StyleConfig,
)
from filmroom.engine.assemble import mmss
from filmroom.style import load_lens, presets_by_id, score, style_from_sliders, verdict

MAX_ROWS = 25


class MomentRow(BaseModel):
    possession_id: str
    time: str
    team: int
    player: str
    outcome: str
    zone: str
    severity: float
    chosen: str
    best_under_style: str
    better_available: bool


class DecisionRow(BaseModel):
    idx: int
    time: str
    player: str
    kind: str
    chosen: str
    is_turning_point: bool


class PossessionView(BaseModel):
    possession_id: str
    match_id: str
    team: int
    start: str
    end: str
    outcome: str
    zone: str
    flagged: bool
    severity: float
    decisions: list[DecisionRow]


class FlipView(BaseModel):
    vs_style: str
    factor: FactorName
    slider: SliderName | None
    contribution: float


class TurningPointView(BaseModel):
    possession_id: str
    decision_idx: int
    time: str
    player: str
    chosen: str
    style_id: str
    best_option_id: str
    best: str
    better_available: bool
    margin: float
    flip: FlipView | None


class OptionRow(BaseModel):
    option_id: str
    action: str
    p_success: float
    p_success_band: str
    danger_gain: float
    score: float
    chosen: bool
    contributions: dict[FactorName, float]


class OptionsView(BaseModel):
    possession_id: str
    decision_idx: int
    style: str
    options: list[OptionRow]


class StyleVerdict(BaseModel):
    style_id: str
    best_option_id: str
    best: str
    better_available: bool
    principle: str | None


class StyleComparison(BaseModel):
    possession_id: str
    a: StyleVerdict
    b: StyleVerdict
    same_verdict: bool
    factor: FactorName | None
    slider: SliderName | None
    contribution: float | None


class SimilarMoment(BaseModel):
    possession_id: str
    similarity: float
    time: str
    player: str
    outcome: str
    zone: str


def slider_for(factor: FactorName) -> SliderName | None:
    return next((s.slider for s in load_lens().sliders if factor in s.gains), None)


class EngineTools:
    def __init__(self, store: Store):
        self.store = store

    def _style(self, style_id: str | None) -> StyleConfig:
        styles = presets_by_id(load_lens())
        if style_id is None:
            return next(iter(styles.values()))
        if style_id not in styles:
            raise ValueError(f"unknown style {style_id}; presets: {', '.join(styles)}")
        return styles[style_id]

    def _possession(self, possession_id: str) -> tuple[Possession, Match]:
        try:
            possession = self.store.possession(possession_id)
        except KeyError as missing:
            raise ValueError(f"unknown possession {possession_id}") from missing
        return possession, self.store.match(possession.match_id)

    def _turning_point(self, possession: Possession) -> Decision:
        if possession.turning_point_idx is None:
            raise ValueError(f"{possession.id} is not flagged, so it has no turning point")
        return possession.decisions[possession.turning_point_idx]

    @staticmethod
    def _option(decision: Decision, option_id: str) -> Option:
        return next(o for o in decision.options if o.id == option_id)

    def list_flagged_moments(
        self,
        match_id: str,
        team: int | None = None,
        style_id: str | None = None,
        outcome: str | None = None,
        zone: str | None = None,
        limit: int = 10,
    ) -> list[MomentRow]:
        """Flagged moments of one match, most severe first: where a move broke down while a better option
        existed. Filter by team (0 or 1), outcome (shot, lost_tackle, lost_pass, out, stoppage) or zone where
        it ended (own, mid, final). Each row has the turning-point player and time, what was chosen and the
        best option under the style (a preset ID; the reference preset if omitted)."""
        try:
            match, possessions = self.store.match(match_id), self.store.match_possessions(match_id)
        except KeyError as missing:
            raise ValueError(f"unknown match {match_id}") from missing
        style = self._style(style_id)
        rows = []
        for p in sorted(possessions, key=lambda p: -p.severity):
            if not p.flagged or any(
                want is not None and have != want
                for want, have in ((team, p.team), (outcome, p.outcome), (zone, p.ended_zone))
            ):
                continue
            decision = self._turning_point(p)
            v = p.verdicts[style.id]
            rows.append(
                MomentRow(
                    possession_id=p.id,
                    time=mmss(decision.t_ms),
                    team=p.team,
                    player=player_name(match, decision.pid),
                    outcome=p.outcome,
                    zone=p.ended_zone,
                    severity=p.severity,
                    chosen=action_phrase(self._option(decision, v.chosen_option_id), match, "en"),
                    best_under_style=action_phrase(self._option(decision, v.best_option_id), match, "en"),
                    better_available=v.better_available,
                )
            )
        return rows[: min(limit, MAX_ROWS)]

    def get_possession(self, possession_id: str) -> PossessionView:
        """One possession from start to end: outcome, zone, severity and every decision in it, with the
        player, time and what they chose. The turning point is the final decision of a flagged possession."""
        possession, match = self._possession(possession_id)
        return PossessionView(
            possession_id=possession.id,
            match_id=possession.match_id,
            team=possession.team,
            start=mmss(possession.start_ms),
            end=mmss(possession.end_ms),
            outcome=possession.outcome,
            zone=possession.ended_zone,
            flagged=possession.flagged,
            severity=possession.severity,
            decisions=[
                DecisionRow(
                    idx=d.idx,
                    time=mmss(d.t_ms),
                    player=player_name(match, d.pid),
                    kind=d.kind,
                    chosen=action_phrase(self._option(d, d.chosen_option_id), match, "en"),
                    is_turning_point=d.is_turning_point,
                )
                for d in possession.decisions
            ],
        )

    def find_turning_point(self, possession_id: str, style_id: str | None = None) -> TurningPointView:
        """Where the move broke down: the turning-point decision of a flagged possession, what was chosen, the
        best option under the style (a preset ID; the reference if omitted), the margin between them, and,
        if this style's verdict differs from the reference, the factor and slider that changed it."""
        possession, match = self._possession(possession_id)
        decision = self._turning_point(possession)
        style = self._style(style_id)
        v = possession.verdicts[style.id]
        flip = v.flip_reason
        return TurningPointView(
            possession_id=possession.id,
            decision_idx=decision.idx,
            time=mmss(decision.t_ms),
            player=player_name(match, decision.pid),
            chosen=action_phrase(self._option(decision, v.chosen_option_id), match, "en"),
            style_id=style.id,
            best_option_id=v.best_option_id,
            best=action_phrase(self._option(decision, v.best_option_id), match, "en"),
            better_available=v.better_available,
            margin=v.margin,
            flip=FlipView(
                vs_style=flip.vs_style_id,
                factor=flip.factor,
                slider=slider_for(flip.factor),
                contribution=flip.contribution,
            )
            if flip
            else None,
        )

    def evaluate_options(
        self,
        possession_id: str,
        style_id: str | None = None,
        risk_tolerance: float | None = None,
        verticality: float | None = None,
        press_trigger: float | None = None,
        line_height: float | None = None,
        decision_idx: int | None = None,
    ) -> OptionsView:
        """Every option at a decision (the turning point unless decision_idx is given), ranked by score under
        a style: a preset ID, or all four sliders between 0 and 1 (risk_tolerance, verticality,
        press_trigger, line_height) for a custom style. Each option shows its success odds, the danger it
        adds, its score and how much each style factor contributed."""
        possession, match = self._possession(possession_id)
        sliders = (risk_tolerance, verticality, press_trigger, line_height)
        if style_id is None and all(s is not None for s in sliders):
            reference = self._style(None)
            custom = Sliders(
                risk_tolerance=risk_tolerance,
                verticality=verticality,
                press_trigger=press_trigger,
                line_height=line_height,
            )
            style = style_from_sliders(load_lens(), reference.with_ball, reference.without_ball, custom)
        else:
            style = self._style(style_id)
        if decision_idx is None:
            decision = self._turning_point(possession)
        elif 0 <= decision_idx < len(possession.decisions):
            decision = possession.decisions[decision_idx]
        else:
            raise ValueError(f"{possession_id} has decisions 0 to {len(possession.decisions) - 1}")
        rows = [
            OptionRow(
                option_id=o.id,
                action=action_phrase(o, match, "en"),
                p_success=o.p_success,
                p_success_band=o.p_success_band,
                danger_gain=o.danger_gain,
                score=round(score(o, style), 4),
                chosen=o.id == decision.chosen_option_id,
                contributions={f: round(style.weights.get(f, 0.0) * v, 4) for f, v in o.factors.items()},
            )
            for o in decision.options
        ]
        rows.sort(key=lambda r: -r.score)
        return OptionsView(
            possession_id=possession.id, decision_idx=decision.idx, style=style.id, options=rows
        )

    def compare_styles(self, possession_id: str, style_a: str, style_b: str) -> StyleComparison:
        """How two presets judge the turning point of a flagged possession: each one's best option, whether
        they agree, and when they don't, the factor that decided the difference, the slider behind it and
        the principle each style card states for that factor."""
        possession, match = self._possession(possession_id)
        decision = self._turning_point(possession)
        a, b = self._style(style_a), self._style(style_b)
        flip = verdict(decision, b, a).flip_reason

        def judged(style: StyleConfig) -> StyleVerdict:
            v = possession.verdicts[style.id]
            principle = next((p.text for p in style.principles if flip and p.factor == flip.factor), None)
            return StyleVerdict(
                style_id=style.id,
                best_option_id=v.best_option_id,
                best=action_phrase(self._option(decision, v.best_option_id), match, "en"),
                better_available=v.better_available,
                principle=principle,
            )

        return StyleComparison(
            possession_id=possession.id,
            a=judged(a),
            b=judged(b),
            same_verdict=flip is None,
            factor=flip.factor if flip else None,
            slider=slider_for(flip.factor) if flip else None,
            contribution=flip.contribution if flip else None,
        )

    def search_similar_situations(
        self, possession_id: str, limit: int = 5, all_matches: bool = False
    ) -> list[SimilarMoment]:
        """Flagged moments most like this one (same kind of decision, where and how it ended, and the style
        factors of what was chosen and what was best), from the same match or from every match."""
        self._possession(possession_id)
        found = self.store.similar(possession_id, self._style(None).id, min(limit, MAX_ROWS), all_matches)
        matches = {m: self.store.match(m) for m in {p.match_id for p, _ in found}}
        similar = []
        for p, similarity in found:
            decision = self._turning_point(p)
            similar.append(
                SimilarMoment(
                    possession_id=p.id,
                    similarity=similarity,
                    time=mmss(decision.t_ms),
                    player=player_name(matches[p.match_id], decision.pid),
                    outcome=p.outcome,
                    zone=p.ended_zone,
                )
            )
        return similar

    def all(self) -> list:
        return [
            self.list_flagged_moments,
            self.get_possession,
            self.find_turning_point,
            self.evaluate_options,
            self.compare_styles,
            self.search_similar_situations,
        ]
