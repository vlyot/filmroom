"""The session pack for half-time or full-time, as a Microsoft Agent Framework workflow where code and agents
take turns:

    select (code) -> compare styles (code) -> themes (theme agent) -> narrate (narrator) -> assemble

Code ranks the moments and counts how other presets would judge them; the theme agent groups them and the
narrator explains each one, both checked by the verifier. Themes fall back to grouping by outcome and zone,
and any narrative not ready in time stays a template, so a pack always comes back.
"""

import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Literal, Never

from agent_framework import (
    Agent,
    Executor,
    Message,
    SupportsChatGetResponse,
    WorkflowBuilder,
    WorkflowContext,
    handler,
)
from pydantic import BaseModel, ValidationError

from filmroom.agents.cache import JsonCache, cache_key
from filmroom.agents.facts import action_phrase, load_language, player_name
from filmroom.agents.llm import purpose
from filmroom.agents.narratives import NarrativeService
from filmroom.agents.narrator import NarrationRequest, prompt
from filmroom.agents.verifier import Rejection, feedback, name_words, verify_themes
from filmroom.api.store import Store, summary_of
from filmroom.contracts.models import (
    Audience,
    Match,
    Narrative,
    PackMoment,
    PackTheme,
    Possession,
    SessionPack,
    Side,
    StyleConfig,
    StyleShift,
)
from filmroom.engine.assemble import mmss
from filmroom.style import flip_reason, load_lens, presets_by_id

log = logging.getLogger("filmroom.session_pack")
MAX_MOMENTS = 10
THEMES_VERSION = 1
THEMES_TIMEOUT_S = 30
NARRATE_TIMEOUT_S = 40


@dataclass(frozen=True)
class PackRequest:
    match_id: str
    team: Side
    style_id: str
    period: Literal["half", "full"]
    audience: Audience
    language: str


@dataclass
class PackDraft:
    """What travels along the workflow, filled in step by step."""

    request: PackRequest
    match: Match
    styles: dict[str, StyleConfig]
    moments: list[Possession] = field(default_factory=list)
    shifts: list[StyleShift] = field(default_factory=list)
    themes: list[PackTheme] = field(default_factory=list)
    narratives: list[Narrative] = field(default_factory=list)

    @property
    def style(self) -> StyleConfig:
        return self.styles[self.request.style_id]

    @property
    def reference(self) -> StyleConfig:
        return next(iter(self.styles.values()))


class ThemeDraft(BaseModel):
    title: str
    summary: str
    possession_ids: list[str]


class ThemesDraft(BaseModel):
    themes: list[ThemeDraft]


class ThemeSet(BaseModel):
    themes: list[PackTheme]


THEME_OPTIONS = {"response_format": ThemesDraft, "temperature": 0.3, "max_tokens": 700}


def fallback_themes(moments: list[Possession], language: str) -> list[PackTheme]:
    lang = load_language(language)
    groups: dict[tuple[str, str], list[str]] = {}
    for p in moments:
        groups.setdefault((p.outcome, p.ended_zone), []).append(p.id)
    return [
        PackTheme(
            title=lang["fallback"]["theme_title"].format(outcome=lang["outcomes"][o], zone=lang["zones"][z]),
            summary=lang["fallback"]["theme_summary"].format(zone=lang["zones"][z]),
            possession_ids=ids,
            status="fallback",
        )
        for (o, z), ids in groups.items()
    ]


class SelectMoments(Executor):
    def __init__(self, store: Store):
        super().__init__(id="select_moments")
        self.store = store

    @handler
    async def select(self, draft: PackDraft, ctx: WorkflowContext[PackDraft]) -> None:
        request = draft.request
        possessions = await asyncio.to_thread(self.store.match_possessions, request.match_id)
        cutoff = draft.match.duration_ms / 2 if request.period == "half" else float("inf")
        flagged = [p for p in possessions if p.flagged and p.team == request.team and p.start_ms < cutoff]
        flagged.sort(key=lambda p: (-p.severity, p.start_ms))
        await ctx.send_message(replace(draft, moments=flagged[:MAX_MOMENTS]))


class CompareStyles(Executor):
    def __init__(self):
        super().__init__(id="compare_styles")

    @handler
    async def compare(self, draft: PackDraft, ctx: WorkflowContext[PackDraft]) -> None:
        shifts = []
        for other in draft.styles.values():
            if other.id == draft.style.id:
                continue
            factors = Counter()
            for p in draft.moments:
                decision = p.decisions[p.turning_point_idx]
                if flip := flip_reason(decision, draft.style, other):
                    factors[flip.factor] += 1
            top = factors.most_common(1)[0][0] if factors else None
            shifts.append(StyleShift(style_id=other.id, name=other.name, changed=factors.total(), factor=top))
        await ctx.send_message(replace(draft, shifts=shifts))


class GroupThemes(Executor):
    def __init__(self, client: SupportsChatGetResponse | None, model: str | None, cache: JsonCache):
        super().__init__(id="group_themes")
        self.agent = Agent(client=client, name="themes", instructions=prompt("themes.md")) if client else None
        self.model = model
        self.cache = cache

    def _moments_message(self, draft: PackDraft) -> str:
        lang = load_language(draft.request.language)
        lines = [f"Write in {lang['name']}. Style: {draft.style.name}. Moments:"]
        for p in draft.moments:
            decision = p.decisions[p.turning_point_idx]
            verdict = p.verdicts[draft.style.id]
            options = {o.id: o for o in decision.options}
            moment = {
                "possession_id": p.id,
                "time": mmss(decision.t_ms),
                "player": player_name(draft.match, decision.pid),
                "outcome": p.outcome,
                "zone": p.ended_zone,
                "chose": action_phrase(options[verdict.chosen_option_id], draft.match, "en"),
                "best_under_style": action_phrase(options[verdict.best_option_id], draft.match, "en"),
                "verdict_changed_by": verdict.flip_reason.factor if verdict.flip_reason else None,
            }
            lines.append(json.dumps(moment))
        return "\n".join(lines)

    async def _ask(self, draft: PackDraft) -> list[PackTheme] | None:
        selected = [p.id for p in draft.moments]
        roster = name_words([p.name for p in draft.match.players] + [t.name for t in draft.match.teams])
        messages = [Message(role="user", contents=[self._moments_message(draft)])]
        rejections: list[Rejection] = []
        for _ in range(2):
            with purpose("themes"):
                response = await asyncio.wait_for(
                    self.agent.run(messages, options=THEME_OPTIONS),
                    THEMES_TIMEOUT_S,
                )
            try:
                themes: ThemesDraft = response.value
            except (ValidationError, ValueError) as error:
                rejections = [Rejection("malformed", f"not the requested JSON: {str(error)[:200]}")]
            else:
                parts = [(t.title, t.summary, t.possession_ids) for t in themes.themes]
                rejections = verify_themes(parts, selected, roster, draft.request.language)
                if not rejections:
                    return [PackTheme(**t.model_dump(), status="verified") for t in themes.themes]
            messages += [
                Message(role="assistant", contents=[response.text]),
                Message(role="user", contents=[feedback(rejections, "grouping")]),
            ]
        log.info(json.dumps({"event": "themes_fallback", "rejections": [r.code for r in rejections]}))
        return None

    def _key(self, draft: PackDraft) -> str:
        moments = [p.model_dump(include={"id", "outcome", "ended_zone", "verdicts"}) for p in draft.moments]
        return cache_key(
            {
                "kind": "themes",
                "version": THEMES_VERSION,
                "model": self.model,
                "style": draft.style.id,
                "language": draft.request.language,
                "moments": moments,
            }
        )

    @handler
    async def group(self, draft: PackDraft, ctx: WorkflowContext[PackDraft]) -> None:
        language, key = draft.request.language, self._key(draft)
        if cached := self.cache.get(key, ThemeSet):
            themes = cached.themes
        elif self.agent is None or not draft.moments:
            themes = fallback_themes(draft.moments, language)
        else:
            try:
                themes = await self._ask(draft) or fallback_themes(draft.moments, language)
            except Exception as error:  # LLM errors, the allowance, timeouts: group by outcome, uncached
                log.warning(json.dumps({"event": "themes_error", "error": repr(error)[:300]}))
                themes = fallback_themes(draft.moments, language)
            else:
                self.cache.put(key, ThemeSet(themes=themes))
        await ctx.send_message(replace(draft, themes=themes))


class Narrate(Executor):
    def __init__(self, narratives: NarrativeService):
        super().__init__(id="narrate")
        self.narratives = narratives

    @handler
    async def narrate(self, draft: PackDraft, ctx: WorkflowContext[PackDraft]) -> None:
        request = draft.request
        requests = [
            NarrationRequest(p, draft.match, draft.style, draft.reference, request.audience, request.language)
            for p in draft.moments
        ]
        narratives = await asyncio.gather(*(self.narratives.wait(r, NARRATE_TIMEOUT_S) for r in requests))
        await ctx.send_message(replace(draft, narratives=list(narratives)))


class Assemble(Executor):
    def __init__(self):
        super().__init__(id="assemble")

    @handler
    async def assemble(self, draft: PackDraft, ctx: WorkflowContext[Never, SessionPack]) -> None:
        request = draft.request
        moments = [
            PackMoment(rank=rank, summary=summary_of(p), verdict=p.verdicts[draft.style.id], narrative=n)
            for rank, (p, n) in enumerate(zip(draft.moments, draft.narratives, strict=True), start=1)
        ]
        pack = SessionPack(
            match_id=request.match_id,
            team=request.team,
            style_id=request.style_id,
            period=request.period,
            audience=request.audience,
            language=request.language,
            themes=draft.themes,
            moments=moments,
            style_shifts=draft.shifts,
        )
        await ctx.yield_output(pack)


class SessionPackBuilder:
    def __init__(
        self,
        store: Store,
        narratives: NarrativeService,
        client: SupportsChatGetResponse | None,
        model: str | None,
        cache: JsonCache,
    ):
        self.store = store
        self.narratives = narratives
        self.client = client
        self.model = model
        self.cache = cache

    async def build(self, request: PackRequest) -> SessionPack:
        """Raises KeyError for an unknown match or style."""
        styles = presets_by_id(load_lens())
        if request.style_id not in styles:
            raise KeyError(f"unknown style: {request.style_id}")
        match = await asyncio.to_thread(self.store.match, request.match_id)
        select, compare = SelectMoments(self.store), CompareStyles()
        group = GroupThemes(self.client, self.model, self.cache)
        narrate, assemble = Narrate(self.narratives), Assemble()
        workflow = (
            WorkflowBuilder(name="session_pack", start_executor=select)
            .add_edge(select, compare)
            .add_edge(compare, group)
            .add_edge(group, narrate)
            .add_edge(narrate, assemble)
            .build()
        )
        result = await workflow.run(PackDraft(request, match, styles))
        return result.get_outputs()[0]
