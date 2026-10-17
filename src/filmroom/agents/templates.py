"""Template narratives: every flagged possession has one for each preset, audience and language, shown at once
and replaced when a verified LLM narrative exists. A template states the same verdict claim the narrator
must make."""

import json
from functools import cache
from pathlib import Path

from filmroom.agents.facts import narrative_facts, turning_point_verdict
from filmroom.contracts.models import Audience, Claim, Match, Narrative, Possession, StyleConfig

TEMPLATES_PATH = Path(__file__).with_name("templates.json")


@cache
def load_templates() -> dict[str, str]:
    return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))


def verdict_claim(possession: Possession, style_id: str) -> Claim:
    verdict = turning_point_verdict(possession, style_id)
    if verdict.better_available:
        return Claim(type="better_option", ref=verdict.best_option_id)
    return Claim(type="chosen_fits_style", ref=verdict.chosen_option_id)


def template_narrative(
    possession: Possession,
    match: Match,
    style: StyleConfig,
    reference: StyleConfig,
    audience: Audience,
    language: str,
) -> Narrative:
    claim = verdict_claim(possession, style.id)
    kind = "better" if claim.type == "better_option" else "fits"
    return Narrative(
        possession_id=possession.id,
        style_id=style.id,
        audience=audience,
        language=language,
        template=load_templates()[f"{audience}.{language}.{kind}"],
        facts=narrative_facts(possession, match, style, reference, language),
        claims=[claim],
        status="template",
    )
