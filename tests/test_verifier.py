from collections.abc import Callable
from dataclasses import dataclass

import pytest

from filmroom.agents.facts import supported_languages
from filmroom.agents.templates import template_narrative
from filmroom.agents.verifier import NarrativeCheck, check_text, name_words, verify_narrative, verify_reply
from filmroom.contracts.models import Claim, Narrative
from filmroom.data.identity import NAMES
from tests.agent_fakes import REFERENCE, STYLE_BY_ID, STYLES, synth

AUDIENCES = ("coach", "player", "fan")
NOT_ON_ANY_CARD = "receiver_space"  # fixed weight, so no rule set states a principle for it


def _clean() -> list[tuple[Narrative, NarrativeCheck]]:
    match, possessions = synth()
    cases = []
    for possession in possessions:
        for style in STYLES:
            for audience in AUDIENCES:
                for language in supported_languages():
                    n = template_narrative(possession, match, style, REFERENCE, audience, language)
                    cases.append((n, NarrativeCheck(possession, style, n.facts, audience, language)))
    return cases


def _codes(n: Narrative, check: NarrativeCheck) -> set[str]:
    return {r.code for r in verify_narrative(n.template, n.claims, check)}


def _with(n: Narrative, template: str | None = None, claims: list[Claim] | None = None) -> Narrative:
    update = {"template": template or n.template, "claims": n.claims if claims is None else claims}
    return n.model_copy(update=update)


def test_accepts_every_clean_template_narrative():
    cases = _clean()
    assert len(cases) == 3 * len(STYLES) * len(AUDIENCES) * 2
    assert [(n.style_id, n.audience, n.language) for n, check in cases if _codes(n, check)] == []


Change = Callable[[Narrative, NarrativeCheck], Narrative]


@dataclass(frozen=True)
class Injection:
    name: str
    code: str
    change: Change
    when: str = "always"  # or "better" / "fits": only narratives whose verdict says so

    def applies(self, check: NarrativeCheck) -> bool:
        better = check.possession.verdicts[check.style.id].better_available
        return self.when == "always" or (self.when == "better") == better


SENTENCES = {
    "digit": {"en": " He had 3 passes on.", "es": " Tenía 3 pases posibles."},
    "number": {"en": " Two defenders closed in.", "es": " Dos defensas cerraron."},
    "real_start": {"en": " Messi was free on the left.", "es": " Messi estaba libre."},
    "real_mid": {"en": " The pass for Salah was on.", "es": " El pase para Salah estaba ahí."},
    "real_full": {"en": " A pass to Mohamed Salah was on.", "es": " Un pase a Mohamed Salah estaba ahí."},
    "alternative": {"en": " A dribble was on instead.", "es": " En lugar de eso, una conducción era mejor."},
    "self_pass": {"en": " It should have been a pass to {tp.player}.", "es": " Faltó un pase a {tp.player}."},
}


def append(text: str | None = None, sentence: str | None = None) -> Change:
    def change(n: Narrative, check: NarrativeCheck) -> Narrative:
        added = text if sentence is None else SENTENCES[sentence][check.language]
        return _with(n, n.template + added)

    return change


def replace(old: str, new: str) -> Change:
    return lambda n, check: _with(n, n.template.replace(old, new, 1))


def claim(kind: str, ref: Callable[[NarrativeCheck], str], keep: bool = False) -> Change:
    return lambda n, check: _with(n, claims=[*(n.claims if keep else []), Claim(type=kind, ref=ref(check))])


def _verdict(check: NarrativeCheck):
    return check.possession.verdicts[check.style.id]


def _not_best(check: NarrativeCheck) -> str:
    verdict = _verdict(check)
    options = check.possession.decisions[verdict.decision_idx].options
    return next(o.id for o in options if o.id != verdict.best_option_id)


def _doubled_phrase(n: Narrative, check: NarrativeCheck) -> Narrative:
    doubled = {"en": "a pass to {chosen.action}", "es": "un pase a {chosen.action}"}[check.language]
    return _with(n, n.template.replace("{chosen.action}", doubled, 1))


def _fictional_name(n: Narrative, check: NarrativeCheck) -> Narrative:
    return _with(n, n.template + f" {NAMES['first'][0]} {NAMES['last'][0]} lost it.")


INJECTIONS = [
    Injection("digit", "digit", append(sentence="digit")),
    Injection("percent", "digit", append(" ({chosen.p_success}%)")),
    Injection("number word", "number_word", append(sentence="number")),
    Injection("unknown slot", "slot_unknown", append(" {alt.player}")),
    Injection("best slot when it fits", "slot_unknown", append(" {best.action}"), "fits"),
    Injection("malformed slot", "slot_malformed", replace("{tp.time}", "{tp.time")),
    Injection("wrong best option", "claim_contradicts", claim("better_option", _not_best), "better"),
    Injection("better option when it fits", "claim_contradicts", claim("better_option", _not_best), "fits"),
    Injection(
        "fits when a better option existed",
        "claim_contradicts",
        claim("chosen_fits_style", lambda c: _verdict(c).chosen_option_id),
        "better",
    ),
    Injection("no verdict claim", "claim_missing", lambda n, c: _with(n, claims=[])),
    Injection("two verdict claims", "claim_missing", lambda n, c: _with(n, claims=[*n.claims, *n.claims])),
    Injection(
        "principle off the card",
        "claim_contradicts",
        claim("style_principle", lambda c: NOT_ON_ANY_CARD, keep=True),
    ),
    Injection("wrong turning point", "claim_contradicts", claim("turning_point", lambda c: "99", keep=True)),
    Injection("real name opening a sentence", "name", append(sentence="real_start")),
    Injection("real name mid-sentence", "name", append(sentence="real_mid")),
    Injection("real full name", "name", append(sentence="real_full")),
    Injection("fictional name outside a slot", "name", _fictional_name),
    Injection("too long", "too_long", append(" and then" * 100)),
    Injection("factor id in the text", "identifier", append(" It broke the switch_of_play idea.")),
    Injection("unit repeated", "unit_repeated", append(" It added +{best.danger_gain} xT."), "better"),
    Injection("phrase opening a sentence", "phrase_opens_sentence", append(" {chosen.action} was rushed.")),
    Injection("phrase doubled", "phrase_doubled", _doubled_phrase),
    Injection(
        "alternative when the choice fits", "claim_contradicts", append(sentence="alternative"), "fits"
    ),
    Injection("decision maker as receiver", "claim_contradicts", append(sentence="self_pass")),
]


@pytest.mark.parametrize("injection", INJECTIONS, ids=lambda i: i.name)
def test_catches_every_injected_error_of_each_kind(injection: Injection):
    applied = missed = 0
    for n, check in _clean():
        if not injection.applies(check):
            continue
        applied += 1
        missed += injection.code not in _codes(injection.change(n, check), check)
    assert applied > 0 and missed == 0


def test_catches_all_injected_errors_in_both_languages():
    caught = total = 0
    for n, check in _clean():
        for injection in INJECTIONS:
            if injection.applies(check):
                total += 1
                caught += bool(_codes(injection.change(n, check), check))
    assert caught == total > 500


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("He found the final third, and one teammate was free in the half-space.", "en"),
        ("Under Possession + High Press, the Mid-Block shape left space.", "en"),
        ("Con Counter + Low Block, un pase al último tercio era la opción.", "es"),
        ("¿Por qué no buscó el pase? Había una línea abierta.", "es"),
    ],
)
def test_allows_articles_football_terms_and_style_names(text, language):
    assert check_text(text, language) == []


@pytest.mark.parametrize(
    ("text", "language"),
    [("The turning point was decision one.", "en"), ("El momento clave fue la decisión uno.", "es")],
)
def test_rejects_a_decision_counted_in_words(text, language):
    # "one" alone is allowed (a better one); counting decisions in words isn't, and was zero-based in a draft
    assert {r.code for r in check_text(text, language)} == {"number_word"}


def test_reply_check_rejects_unknown_possessions_and_allows_roster_names():
    _, possessions = synth()
    roster = name_words(["Kofi Mensah", "Aled Brook", "Harrow Vale"])
    known = {p.id for p in possessions}
    text = "Kofi Mensah lost the ball here, and Harrow Vale broke."
    assert verify_reply(text, [possessions[0].id], known, roster, "en") == []
    codes = {r.code for r in verify_reply("Salah lost it.", ["nope-1"], known, roster, "en")}
    assert codes == {"name", "unknown_possession"}


def test_reply_check_rejects_numbers_and_braces():
    codes = {r.code for r in verify_reply("He lost it twice {here}.", [], set(), frozenset(), "en")}
    assert codes == {"number_word", "slot_malformed"}


def test_fits_and_better_verdicts_both_occur_in_the_synthetic_set():
    _, possessions = synth()
    kinds = {p.verdicts[s.id].better_available for p in possessions for s in STYLES}
    assert kinds == {True, False}
    assert any(p.verdicts[STYLE_BY_ID["direct-mid-block"].id].flip_reason for p in possessions)


def test_rejects_a_fictional_name_even_where_it_opens_a_sentence():
    pooled = next(name for name in NAMES["first"] if name.lower().endswith("o"))
    assert {r.code for r in check_text(f"{pooled} was free.", "en")} == {"name"}
    assert check_text(f"{pooled} was free.", "en", frozenset({pooled})) == []


def test_rejects_a_sentence_that_opens_in_lowercase():
    codes = {r.code for r in check_text("at the turning point he went long. It broke down.", "en")}
    assert codes == {"lowercase"}
