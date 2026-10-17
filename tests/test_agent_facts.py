import pytest

from filmroom.agents.facts import (
    action_phrase,
    format_fact,
    narrative_facts,
    render,
    supported_languages,
)
from filmroom.agents.templates import load_templates, template_narrative
from filmroom.contracts.models import Fact, Option, template_slots
from tests.agent_fakes import REFERENCE, STYLE_BY_ID, STYLES, synth

AUDIENCES = ("coach", "player", "fan")


def _possession(suffix: str):
    match, possessions = synth()
    return match, next(p for p in possessions if p.id.endswith(suffix))


def test_names_the_styles_best_option_not_the_engines_best_pass():
    match, possession = _possession("-0")
    for style in STYLES:
        verdict = possession.verdicts[style.id]
        best = next(
            o for o in possession.decisions[verdict.decision_idx].options if o.id == verdict.best_option_id
        )
        facts = narrative_facts(possession, match, style, REFERENCE, "en")
        receiver = next(p.name for p in match.players if p.pid == best.target_pid)
        assert facts["best.action"].value == f"a pass to {receiver}"
        assert facts["best.danger_gain"].value == best.danger_gain
        assert not {"alt.player", "best.player", "decisions.after_tp"} & set(facts)


def test_leaves_out_best_slots_when_the_choice_fits_the_style():
    match, shot = _possession("-450")
    fits = narrative_facts(shot, match, STYLE_BY_ID["counter-low-block"], REFERENCE, "en")
    assert not any(slot.startswith("best.") for slot in fits)
    better = narrative_facts(shot, match, REFERENCE, REFERENCE, "en")
    assert {"best.action", "best.p_success", "best.p_success_band", "best.danger_gain"} <= set(better)


def test_adds_flip_slots_only_when_the_verdict_flipped_against_the_reference():
    match, possession = _possession("-0")
    assert "flip.factor" not in narrative_facts(possession, match, REFERENCE, REFERENCE, "en")
    flipped = narrative_facts(possession, match, STYLE_BY_ID["direct-mid-block"], REFERENCE, "es")
    assert flipped["flip.factor"].value == "el cambio de orientación"
    assert flipped["flip.vs_style"].value == REFERENCE.name


def test_resolves_every_template_slot_for_every_preset_audience_and_language():
    match, possessions = synth()
    assert set(supported_languages()) == {"en", "es"}
    assert len(load_templates()) == len(AUDIENCES) * 2 * len(supported_languages())
    for possession in possessions:
        for style in STYLES:
            for audience in AUDIENCES:
                for language in supported_languages():
                    n = template_narrative(possession, match, style, REFERENCE, audience, language)
                    assert template_slots(n.template) <= set(n.facts)
                    assert "{" not in render(n.template, n.facts, language)


def test_describes_every_kind_of_action_in_each_language():
    match, _ = synth()
    mate = match.players[3]

    def option(kind, target):
        return Option(
            id="d0.x", kind=kind, target_pid=target, target_xy=None, p_success=0.5,
            p_success_band="medium", danger_gain=0.0, factors={},
        )  # fmt: skip

    assert action_phrase(option("pass", mate.pid), match, "en") == f"a pass to {mate.name}"
    assert action_phrase(option("pass", None), match, "en") == "a pass into space"
    assert action_phrase(option("carry", None), match, "es") == "una conducción"
    assert action_phrase(option("shot", None), match, "es") == "un disparo"


@pytest.mark.parametrize(
    ("fact", "language", "text"),
    [
        (Fact(value=0.784, kind="prob"), "en", "78%"),
        (Fact(value=0.784, kind="prob"), "es", "78 %"),
        (Fact(value=0.0512, kind="xt"), "en", "+0.051 xT"),
        (Fact(value=-0.0512, kind="xt"), "es", "-0,051 xT"),
        (Fact(value="high", kind="band"), "es", "alta"),
        (Fact(value=3, kind="count"), "en", "3"),
    ],
)
def test_formats_slot_values_for_each_locale(fact, language, text):
    assert format_fact(fact, language) == text
