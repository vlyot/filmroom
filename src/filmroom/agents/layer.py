"""The agent layer as the API sees it: built live from settings, or offline (no key, CI, the bundle exporter),
where narratives are templates or cached ones and the analyst reports itself offline."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from starlette.routing import BaseRoute

from filmroom.agents.analyst import Analyst, http_tools
from filmroom.agents.cache import JsonCache
from filmroom.agents.llm import LlmBudget, make_chat_client
from filmroom.agents.mcp_server import build_mcp
from filmroom.agents.narratives import NarrativeService
from filmroom.agents.narrator import NarrationRequest, Narrator
from filmroom.agents.session_pack import SessionPackBuilder
from filmroom.agents.tools import EngineTools
from filmroom.api.store import Store
from filmroom.config import Settings
from filmroom.contracts.models import Audience
from filmroom.style import load_lens, presets_by_id


@dataclass
class AgentLayer:
    store: Store
    narratives: NarrativeService
    analyst: Analyst
    packs: SessionPackBuilder
    mcp: FastMCP

    @classmethod
    def from_settings(cls, settings: Settings, store: Store) -> "AgentLayer":
        budget = LlmBudget(settings.llm_daily_token_limit)
        client = make_chat_client(settings, budget)
        narrator = Narrator(client, settings.mistral_chat_model) if client else None
        model = settings.mistral_chat_model
        cache = JsonCache(settings.cache_dir / "agents")
        narratives = NarrativeService(narrator, cache, budget, model, settings.narrator_concurrency)
        return cls(
            store,
            narratives,
            Analyst(client, model, store, http_tools(settings.mcp_url)),
            SessionPackBuilder(store, narratives, client, model, cache),
            build_mcp(EngineTools(store)),
        )

    @classmethod
    def offline(cls, store: Store, cache: JsonCache | None = None, model: str | None = None) -> "AgentLayer":
        cache = cache or JsonCache(None)
        narratives = NarrativeService(None, cache, model=model)
        return cls(
            store,
            narratives,
            Analyst(None, model, store, None),
            SessionPackBuilder(store, narratives, None, model, cache),
            build_mcp(EngineTools(store)),
        )

    @property
    def live(self) -> bool:
        return self.narratives.live

    def narration(
        self, possession_id: str, style_id: str, audience: Audience, language: str
    ) -> NarrationRequest:
        """Resolves a narrative request; raises KeyError for an unknown possession or style, or a possession
        that isn't flagged. The caller checks the language is supported."""
        styles = presets_by_id(load_lens())
        if style_id not in styles:
            raise KeyError(f"unknown style: {style_id}")
        possession = self.store.possession(possession_id)
        if not possession.flagged:
            raise KeyError(f"not flagged: {possession_id}")
        style, reference = styles[style_id], next(iter(styles.values()))
        match = self.store.match(possession.match_id)
        return NarrationRequest(possession, match, style, reference, audience, language)

    def mcp_routes(self) -> list[BaseRoute]:
        """The MCP endpoint (/mcp), to add to the API's routes."""
        return self.mcp.streamable_http_app().routes

    @asynccontextmanager
    async def lifespan(self, app) -> AsyncIterator[None]:
        async with self.mcp.session_manager.run():
            self.narratives.start()
            try:
                yield
            finally:
                await self.narratives.stop()
