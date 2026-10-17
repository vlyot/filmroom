"""Narrative slots for one possession under one style, in one language, and the code that fills them.

The slots come from the verdict under the active style, not from the engine's `alt.*` facts: those name the
most valuable pass, which a style can rank below a dribble, a shot or another pass. When the choice was the
best option under the style there are no `best.*` slots at all, so a narrative can't name a better option.
"""

import json
from functools import cache
from pathlib import Path

from filmroom.contracts.models import SLOT, Fact, Match, Option, Possession, StyleConfig, Verdict
from filmroom.engine.assemble import mmss

LANGUAGES_DIR = Path(__file__).with_name("languages")


@cache
def load_language(code: str) -> dict:
    path = LANGUAGES_DIR / f"{code}.json"
    if not path.exists():
        raise KeyError(f"unsupported language: {code}")
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def supported_languages() -> tuple[str, ...]:
    return tuple(sorted(p.stem for p in LANGUAGES_DIR.glob("*.json")))


def player_name(match: Match, pid: int) -> str:
    return next(p.name for p in match.players if p.pid == pid)


def action_phrase(option: Option, match: Match, language: str) -> str:
    actions = load_language(language)["actions"]
    if option.kind == "pass":
        if option.target_pid is None:
            return actions["space"]
        return actions["pass"].format(player=player_name(match, option.target_pid))
    return actions[option.kind]


def turning_point_verdict(possession: Possession, style_id: str) -> Verdict:
    if possession.turning_point_idx is None or style_id not in possession.verdicts:
        raise KeyError(f"no verdict for {possession.id} / {style_id}")
    return possession.verdicts[style_id]


def narrative_facts(
    possession: Possession, match: Match, style: StyleConfig, reference: StyleConfig, language: str
) -> dict[str, Fact]:
    verdict = turning_point_verdict(possession, style.id)
    decision = possession.decisions[verdict.decision_idx]
    options = {o.id: o for o in decision.options}
    chosen = options[verdict.chosen_option_id]
    facts = {
        "tp.player": Fact(value=player_name(match, decision.pid), kind="player"),
        "tp.time": Fact(value=mmss(decision.t_ms), kind="text"),
        "chosen.action": Fact(value=action_phrase(chosen, match, language), kind="text"),
        "chosen.p_success": Fact(value=chosen.p_success, kind="prob"),
        "chosen.p_success_band": Fact(value=chosen.p_success_band, kind="band"),
        "style.name": Fact(value=style.name, kind="text"),
    }
    if verdict.better_available:
        best = options[verdict.best_option_id]
        facts |= {
            "best.action": Fact(value=action_phrase(best, match, language), kind="text"),
            "best.p_success": Fact(value=best.p_success, kind="prob"),
            "best.p_success_band": Fact(value=best.p_success_band, kind="band"),
            "best.danger_gain": Fact(value=best.danger_gain, kind="xt"),
        }
    if verdict.flip_reason is not None:
        factor = load_language(language)["factors"][verdict.flip_reason.factor]
        facts |= {
            "flip.factor": Fact(value=factor, kind="text"),
            "flip.vs_style": Fact(value=reference.name, kind="text"),
        }
    return facts


def format_fact(fact: Fact, language: str) -> str:
    """Locale formatting for one slot value. The web app's slot filler follows the same rules."""
    lang = load_language(language)
    match fact.kind:
        case "prob":
            return lang["percent"].format(value=round(float(fact.value) * 100))
        case "xt":
            return f"{float(fact.value):+.3f} xT".replace(".", lang["decimal"])
        case "metres":
            return f"{float(fact.value):.0f} m"
        case "count":
            return str(int(fact.value))
        case "band":
            return lang["bands"][str(fact.value)]
        case _:
            return str(fact.value)


def render(template: str, facts: dict[str, Fact], language: str) -> str:
    return SLOT.sub(lambda m: format_fact(facts[m.group(1)], language), template)
