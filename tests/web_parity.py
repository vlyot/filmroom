"""What the web app's TypeScript ports must reproduce, on the synthetic match: style scoring
(web/src/lib/lens.ts) and narrative slots (web/src/lib/narrative.ts). Written to contracts/parity.json; a test
fails when the file is stale, and the web tests read it. Synthetic data only, so it is safe to commit.

Usage: uv run python -m tests.web_parity
"""

import json
from typing import get_args

from filmroom.agents.facts import format_fact, narrative_facts, render, supported_languages
from filmroom.agents.templates import template_narrative
from filmroom.contracts.models import Audience, Fact, Sliders
from filmroom.style import load_lens, presets, public_lens, style_from_sliders, verdict
from tests.agent_fakes import synth
from tests.conftest import REPO

GOLDEN = REPO / "contracts" / "parity.json"
CUSTOM_SLIDERS = [
    Sliders(risk_tolerance=0.9, verticality=0.1, press_trigger=0.5, line_height=0.3),
    Sliders(risk_tolerance=0.0, verticality=1.0, press_trigger=1.0, line_height=0.0),
    Sliders(risk_tolerance=0.35, verticality=0.65, press_trigger=0.15, line_height=0.85),
]
FORMAT_FACTS = [
    Fact(value=0.784, kind="prob"),
    Fact(value=0.005, kind="prob"),
    Fact(value=0.0504, kind="xt"),
    Fact(value=-0.0126, kind="xt"),
    Fact(value=12.6, kind="metres"),
    Fact(value=3, kind="count"),
    Fact(value="medium", kind="band"),
    Fact(value="Upperdale", kind="text"),
]


def build_golden() -> dict:
    match, possessions = synth()
    lens = load_lens()
    styles = presets(lens)
    reference = styles[0]
    customs = [
        style_from_sliders(lens, reference.with_ball, reference.without_ball, s) for s in CUSTOM_SLIDERS
    ]
    cases = []
    for possession in possessions:
        decision = possession.decisions[possession.turning_point_idx]
        for style in [*styles, *customs]:
            judged = verdict(decision, style, reference)
            seen = possession.model_copy(update={"verdicts": {**possession.verdicts, style.id: judged}})
            narratives = {}
            for audience in get_args(Audience):
                for language in supported_languages():
                    narrative = template_narrative(seen, match, style, reference, audience, language)
                    narratives[f"{audience}.{language}"] = {
                        "template": narrative.template,
                        "claims": [c.model_dump() for c in narrative.claims],
                        "text": render(narrative.template, narrative.facts, language),
                    }
            facts = {
                language: {
                    k: f.model_dump()
                    for k, f in narrative_facts(seen, match, style, reference, language).items()
                }
                for language in supported_languages()
            }
            cases.append(
                {
                    "possession_id": possession.id,
                    "style": style.model_dump(mode="json"),
                    "verdict": judged.model_dump(mode="json"),
                    "facts": facts,
                    "narratives": narratives,
                }
            )
    return {
        "lens": public_lens(lens).model_dump(mode="json"),
        "styles": [s.model_dump(mode="json") for s in styles],
        "match": match.model_dump(mode="json"),
        "possessions": [p.model_dump(mode="json") for p in possessions],
        "cases": cases,
        "formats": [
            {"fact": f.model_dump(), "language": language, "text": format_fact(f, language)}
            for f in FORMAT_FACTS
            for language in supported_languages()
        ],
    }


def render_golden() -> str:
    return json.dumps(build_golden(), indent=1, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    GOLDEN.write_text(render_golden(), encoding="utf-8")
    print(f"wrote {GOLDEN}")
