"""The verifier: plain code that decides whether LLM text may reach the UI.

Numbers and names reach a narrative only through slots, so the text around them may hold no digit, no
spelled-out number and no name: any capitalised word that doesn't open a sentence must be a style or
rule-set name, and a word that opens a sentence must be a common opener in that language or end like an
ordinary word (-ing, -tion, -mente...). A name that happens to end that way can still open a sentence; the
prompts ask for names through slots, and that residual is accepted. Claims are checked
against the verdict under the active style. Analyst and theme replies follow the same text rules, except
that the match's fictional names are allowed, and every possession they cite must exist.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

from filmroom.agents.facts import load_language
from filmroom.contracts.models import SLOT, Audience, Claim, Fact, Possession, StyleConfig, template_slots
from filmroom.data.identity import NAMES
from filmroom.style import load_lens

PLACEHOLDER = "\x00"
TOKEN = re.compile(rf"{PLACEHOLDER}|[^\W\d_]+(?:['’\-][^\W\d_]+)*|[.!?…\n]")
SENTENCE_END = set(".!?…\n")
IDENTIFIER = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
PHRASES = ("chosen.action", "best.action", "flip.factor")  # lowercase phrases: never open a sentence
MAX_LENGTH: dict[Audience, int] = {"coach": 700, "player": 500, "fan": 350}


@dataclass(frozen=True)
class Rejection:
    code: str  # digit, number_word, name, slot_unknown, slot_malformed, claim_missing, claim_contradicts, ...
    detail: str


@cache
def _name_pool() -> frozenset[str]:
    """Every word FilmRoom's fictional names and clubs are made of: never written outside a slot or the
    roster the text may name."""
    return frozenset(word for words in NAMES.values() for name in words for word in name.split())


@cache
def _lens_words() -> frozenset[str]:
    lens = load_lens()
    names = [p.name for p in lens.presets] + [r.name for r in lens.rule_sets]
    return frozenset(word for name in names for word in name.replace("+", " ").split())


@cache
def _number_words(language: str) -> re.Pattern[str]:
    words = sorted(load_language(language)["number_words"], key=len, reverse=True)
    return re.compile(rf"(?<![\w\-])({'|'.join(map(re.escape, words))})(?![\w\-])", re.IGNORECASE)


def name_words(names: Iterable[str]) -> frozenset[str]:
    return frozenset(word for name in names for word in name.split())


def check_text(text: str, language: str, allowed_names: frozenset[str] = frozenset()) -> list[Rejection]:
    """Rules for any LLM text, with slots already replaced by PLACEHOLDER."""
    lang = load_language(language)
    rejections = []
    if not text.strip(PLACEHOLDER + " "):
        rejections.append(Rejection("empty", "the text is empty"))
    if digits := re.findall(r"\d+", text):
        rejections.append(Rejection("digit", f"digits outside slots: {', '.join(digits)}"))
    if "%" in text:
        rejections.append(Rejection("digit", "a percent sign outside a slot"))
    if words := _number_words(language).findall(text):
        rejections.append(Rejection("number_word", f"spelled-out numbers: {', '.join(words)}"))
    if identifiers := IDENTIFIER.findall(text):
        detail = f"code identifiers belong in claims, not the text: {', '.join(identifiers)}"
        rejections.append(Rejection("identifier", detail))
    allowed = _lens_words() | allowed_names | set(lang["allowed_capitalised"])
    starters = set(lang["sentence_starters"])
    suffixes = tuple(lang["starter_suffixes"])
    at_start = True
    for token in TOKEN.findall(text):
        if token in SENTENCE_END:
            at_start = True
            continue
        opener = at_start and (token.lower() in starters or token.lower().endswith(suffixes))
        named = token in _name_pool() or not opener
        if token != PLACEHOLDER and token[0].isupper() and token not in allowed and named:
            rejections.append(Rejection("name", f"'{token}' looks like a name; names go through slots"))
        elif at_start and token != PLACEHOLDER and token[0].islower():
            rejections.append(Rejection("lowercase", f"the sentence starting '{token}' needs a capital"))
        at_start = False
    return rejections


@dataclass(frozen=True)
class NarrativeCheck:
    possession: Possession
    style: StyleConfig
    facts: dict[str, Fact]
    audience: Audience
    language: str


def _check_claims(claims: list[Claim], check: NarrativeCheck) -> list[Rejection]:
    verdict = check.possession.verdicts[check.style.id]
    card = {p.factor for p in check.style.principles}
    rejections = []
    if sum(c.type in ("better_option", "chosen_fits_style") for c in claims) != 1:
        message = "state the verdict with exactly one better_option or chosen_fits_style claim"
        rejections.append(Rejection("claim_missing", message))
    for claim in claims:
        wrong = None
        match claim.type:
            case "better_option" if not verdict.better_available:
                wrong = f"under {check.style.name} the choice itself was the best option"
            case "better_option" if claim.ref != verdict.best_option_id:
                wrong = f"the best option is {verdict.best_option_id}, not {claim.ref}"
            case "chosen_fits_style" if verdict.better_available:
                wrong = f"under {check.style.name} {verdict.best_option_id} was better than the choice"
            case "chosen_fits_style" if claim.ref != verdict.chosen_option_id:
                wrong = f"the choice was {verdict.chosen_option_id}, not {claim.ref}"
            case "turning_point" if claim.ref != str(verdict.decision_idx):
                wrong = f"the turning point is decision {verdict.decision_idx}, not {claim.ref}"
            case "style_principle" if claim.ref not in card:
                wrong = f"{claim.ref} is not a principle on the {check.style.name} card"
        if wrong:
            rejections.append(Rejection("claim_contradicts", wrong))
    return rejections


def verify_narrative(template: str, claims: list[Claim], check: NarrativeCheck) -> list[Rejection]:
    rejections = [
        Rejection("slot_unknown", f"{{{slot}}} is not an available slot")
        for slot in sorted(template_slots(template) - set(check.facts))
    ]
    stripped = SLOT.sub(PLACEHOLDER, template)
    if "{" in stripped or "}" in stripped:
        rejections.append(Rejection("slot_malformed", "braces outside a well-formed {slot}"))
    for slot, fact in check.facts.items():
        written = re.escape(f"{{{slot}}}")
        if fact.kind == "xt" and re.search(rf"\+\s*{written}|{written}\s*(de\s+)?xT", template):
            rejections.append(Rejection("unit_repeated", f"{{{slot}}} already carries its sign and xT"))
        blockers = "|".join(load_language(check.language)["phrase_blockers"])
        if slot.endswith(".action") and re.search(rf"\b(?:{blockers})\s+{written}", template, re.IGNORECASE):
            detail = f"{{{slot}}} starts with its own article and names the receiver; don't repeat them"
            rejections.append(Rejection("phrase_doubled", detail))
        if slot in PHRASES and re.search(rf"(?:^|[.!?…]\s+)[¿¡]?{written}", template):
            detail = f"{{{slot}}} is lowercase; don't open a sentence with it"
            rejections.append(Rejection("phrase_opens_sentence", detail))
    lang = load_language(check.language)
    if re.search(rf"\b(?:{lang['receiver_before']})\s+\{{tp\.player\}}", template, re.IGNORECASE):
        detail = "{tp.player} made the decision, so they can't receive the pass"
        rejections.append(Rejection("claim_contradicts", detail))
    if not check.possession.verdicts[check.style.id].better_available:
        lowered = stripped.lower()
        if said := [m for m in lang["alternative_markers"] if re.search(rf"\b{m}\b", lowered)]:
            detail = f"the choice was the best option, so name no alternative ({', '.join(said)})"
            rejections.append(Rejection("claim_contradicts", detail))
    if len(template) > MAX_LENGTH[check.audience]:
        rejections.append(Rejection("too_long", f"longer than {MAX_LENGTH[check.audience]} characters"))
    return rejections + check_text(stripped, check.language) + _check_claims(claims, check)


def verify_reply(
    text: str, possession_ids: list[str], known_ids: set[str], roster: frozenset[str], language: str
) -> list[Rejection]:
    rejections = check_text(text, language, roster)
    if "{" in text or "}" in text:
        rejections.append(Rejection("slot_malformed", "replies have no slots; write no braces"))
    rejections += [
        Rejection("unknown_possession", f"{pid} is not a possession the tools returned")
        for pid in possession_ids
        if pid not in known_ids
    ]
    return rejections


def feedback(rejections: list[Rejection], what: str) -> str:
    """The retry prompt: why the verifier rejected the last draft."""
    reasons = "\n".join(f"- {r.code}: {r.detail}" for r in rejections)
    return f"The verifier rejected that {what}:\n{reasons}\nWrite it again, following every rule."


def verify_themes(
    themes: list[tuple[str, str, list[str]]], selected: list[str], roster: frozenset[str], language: str
) -> list[Rejection]:
    """Themes (title, summary, possession IDs) must split the selected moments: each in exactly one theme,
    one to four themes, and text that passes the same rules as an analyst reply."""
    rejections = []
    if not 1 <= len(themes) <= 4:
        detail = f"{len(themes)} themes; group the moments into one to four"
        rejections.append(Rejection("theme_count", detail))
    placed = [pid for _, _, ids in themes for pid in ids]
    if sorted(placed) != sorted(selected):
        missing = sorted(set(selected) - set(placed))
        extra = sorted({p for p in placed if p not in selected or placed.count(p) > 1})
        detail = f"put every moment in exactly one theme; missing {missing}, unknown or repeated {extra}"
        rejections.append(Rejection("theme_partition", detail))
    for title, summary, _ in themes:
        rejections += check_text(title, language, roster) + check_text(summary, language, roster)
    return rejections
