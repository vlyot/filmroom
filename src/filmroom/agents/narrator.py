"""The narrator agent: one call per flagged moment, audience, language and style. It writes slot text and
claims; the verifier checks them; one rejection earns a retry with the reasons, a second falls back to the
template. LLM errors (rate limits, the allowance, timeouts) propagate so the caller can retry later instead
of caching a failure."""

import asyncio
import json
from dataclasses import dataclass
from functools import cache, cached_property
from pathlib import Path

from agent_framework import Agent, Message, SupportsChatGetResponse
from pydantic import BaseModel, ValidationError

from filmroom.agents.cache import cache_key
from filmroom.agents.facts import format_fact, load_language, narrative_facts, turning_point_verdict
from filmroom.agents.llm import purpose
from filmroom.agents.templates import template_narrative
from filmroom.agents.verifier import PHRASES, NarrativeCheck, Rejection, feedback, verify_narrative
from filmroom.contracts.models import Audience, Claim, Fact, Match, Narrative, Possession, StyleConfig

NARRATOR_VERSION = 4
PROMPTS_DIR = Path(__file__).with_name("prompts")
TIMEOUT_S = 20
SLOT_MEANINGS = {
    "tp.player": "the player who made the decision",
    "tp.time": "the match clock at the turning point, as minutes:seconds",
    "chosen.action": "what the player chose, naming the receiver of a pass",
    "chosen.p_success": "the success odds of what the player chose, a percentage with its sign",
    "chosen.p_success_band": "an adjective (low, medium, high) for those odds",
    "style.name": "the coach's style the moment is judged under",
    "best.action": "the best option under this style, naming the receiver of a pass",
    "best.p_success": "the success odds of the best option, a percentage with its sign",
    "best.p_success_band": "an adjective (low, medium, high) for those odds",
    "best.danger_gain": "the danger the best option would have added, already signed and in xT: write it "
    "alone, with no + before it and no xT after it",
    "flip.factor": "the factor that changed the verdict against the reference style, in words",
    "flip.vs_style": "the reference style the verdict changed against",
}


@cache
def prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


class NarratorDraft(BaseModel):
    text: str
    claims: list[Claim]


DRAFT_OPTIONS = {"response_format": NarratorDraft, "temperature": 0.4, "max_tokens": 400}


@dataclass(frozen=True)
class NarrationRequest:
    possession: Possession
    match: Match
    style: StyleConfig
    reference: StyleConfig
    audience: Audience
    language: str

    @cached_property
    def facts(self) -> dict[str, Fact]:
        return narrative_facts(self.possession, self.match, self.style, self.reference, self.language)

    @property
    def check(self) -> NarrativeCheck:
        return NarrativeCheck(self.possession, self.style, self.facts, self.audience, self.language)

    def template(self) -> Narrative:
        return template_narrative(
            self.possession, self.match, self.style, self.reference, self.audience, self.language
        )

    def cache_key(self, model: str) -> str:
        return cache_key(
            {
                "kind": "narrative",
                "version": NARRATOR_VERSION,
                "model": model,
                "possession": self.possession.id,
                "style": self.style.model_dump(),
                "audience": self.audience,
                "language": self.language,
                "facts": {k: v.model_dump() for k, v in self.facts.items()},
                "verdict": turning_point_verdict(self.possession, self.style.id).model_dump(),
            }
        )


def _meaning(slot: str, fact: Fact, lang: dict) -> str:
    meaning = SLOT_MEANINGS[slot]
    if fact.kind == "band":
        meaning += f"; write it as '{lang['band_usage'].format(slot=f'{{{slot}}}')}'"
    return meaning


def moment_message(request: NarrationRequest) -> str:
    """Everything the narrator may say about one moment: the audience, the language, the style card, the
    verdict and the slots it may use, with values shown for meaning only."""
    lang = load_language(request.language)
    verdict = turning_point_verdict(request.possession, request.style.id)
    if verdict.better_available:
        stated = f"a better option existed: best option id {verdict.best_option_id}"
    else:
        stated = f"the choice was the best option under this style: id {verdict.chosen_option_id}"
    lines = [
        f"Audience: {request.audience}. {json.loads(prompt('audiences.json'))[request.audience]}",
        f"Language: {lang['name']}. Write the whole text in {lang['name']}. {lang['prompt_note']}",
        f"Style: {request.style.name}. Principles on its card (factor: principle):",
        *(f"- {p.factor}: {p.text}" for p in request.style.principles),
        f"Verdict: {stated}; the choice was {verdict.chosen_option_id}.",
    ]
    if verdict.flip_reason is not None:
        lines.append(
            f"Against {request.reference.name} this verdict changed, mostly because of {{flip.factor}}."
        )
    lines += [
        f"Moment: the possession ended with outcome '{request.possession.outcome}' in the "
        f"'{request.possession.ended_zone}' zone; the turning point is decision {verdict.decision_idx}.",
        "Slots you may use: what each means, and its value only so you understand it (never copy a value):",
        *(
            f"- {{{slot}}}{' (phrase)' if slot in PHRASES else ''}: {_meaning(slot, fact, lang)}. "
            f"Value: {format_fact(fact, request.language)}"
            for slot, fact in request.facts.items()
        ),
    ]
    return "\n".join(lines)


@dataclass(frozen=True)
class NarrationResult:
    narrative: Narrative
    rejections: list[Rejection]  # from the last attempt; empty when verified


class Narrator:
    def __init__(self, client: SupportsChatGetResponse, model: str):
        self.model = model
        self.agent = Agent(client=client, name="narrator", instructions=prompt("narrator.md"))

    async def generate(self, request: NarrationRequest) -> NarrationResult:
        messages = [Message(role="user", contents=[moment_message(request)])]
        rejections: list[Rejection] = []
        for _ in range(2):
            with purpose("narrator"):
                response = await asyncio.wait_for(
                    self.agent.run(messages, options=DRAFT_OPTIONS),
                    TIMEOUT_S,
                )
            try:
                draft: NarratorDraft = response.value
            except (ValidationError, ValueError) as error:
                rejections = [Rejection("malformed", f"not the requested JSON: {str(error)[:200]}")]
            else:
                rejections = verify_narrative(draft.text, draft.claims, request.check)
                if not rejections:
                    narrative = Narrative(
                        possession_id=request.possession.id,
                        style_id=request.style.id,
                        audience=request.audience,
                        language=request.language,
                        template=draft.text,
                        facts=request.facts,
                        claims=draft.claims,
                        status="verified",
                        model=self.model,
                    )
                    return NarrationResult(narrative, [])
            messages += [
                Message(role="assistant", contents=[response.text]),
                Message(role="user", contents=[feedback(rejections, "narrative")]),
            ]
        failed = request.template().model_copy(update={"status": "failed", "model": self.model})
        return NarrationResult(failed, rejections)
