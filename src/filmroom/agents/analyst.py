"""The analyst agent (ask-the-analyst chat): a tool-calling Agent Framework agent over the engine's MCP tools.

It writes no numbers; it cites possessions, and the UI shows their numbers from the engine. The verifier
checks every answer (no numbers, only fictional names, only possessions that exist); one rejection earns a
retry with the reasons, a second returns a canned line with the moments it found. Without an LLM, or once
the day's allowance is spent or a call fails, it reports itself offline.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from agent_framework import Agent, MCPStreamableHTTPTool, Message, SupportsChatGetResponse
from pydantic import BaseModel, ValidationError

from filmroom.agents.facts import load_language
from filmroom.agents.llm import purpose
from filmroom.agents.narrator import prompt
from filmroom.agents.verifier import Rejection, feedback, name_words, verify_reply
from filmroom.api.store import Store
from filmroom.contracts.models import AnalystReply, AnalystRequest
from filmroom.style import load_lens, presets_by_id

log = logging.getLogger("filmroom.analyst")
TIMEOUT_S = 60

ToolsFactory = Callable[[], AbstractAsyncContextManager[MCPStreamableHTTPTool]]


class AnalystDraft(BaseModel):
    text: str
    possession_ids: list[str]


def http_tools(url: str) -> ToolsFactory:
    """The engine tools over MCP at `url` (the API's own /mcp), connected for one answer."""

    @asynccontextmanager
    async def connect() -> AsyncIterator[MCPStreamableHTTPTool]:
        async with MCPStreamableHTTPTool("filmroom_engine", url, load_prompts=False) as tool:
            yield tool

    return connect


class Analyst:
    def __init__(
        self,
        client: SupportsChatGetResponse | None,
        model: str | None,
        store: Store,
        tools: ToolsFactory | None,
    ):
        self.client = client
        self.model = model
        self.store = store
        self.tools = tools

    def _context(self, request: AnalystRequest) -> str:
        lang = load_language(request.language)
        styles = presets_by_id(load_lens())
        lines = [
            f"Answer in {lang['name']}.",
            "Style presets (id: name): " + "; ".join(f"{s.id}: {s.name}" for s in styles.values()),
            f"The coach's style: {request.style_id or next(iter(styles))}.",
        ]
        if request.match_id:
            match = self.store.match(request.match_id)
            teams = ", ".join(f"team {t.side} is {t.name}" for t in match.teams)
            lines.append(f"Match {match.id}: {match.title} ({teams}).")
        return "\n".join(lines)

    def _existing(self, possession_ids: list[str]) -> set[str]:
        found = set()
        for pid in possession_ids:
            try:
                self.store.possession(pid)
            except KeyError:
                continue
            found.add(pid)
        return found

    def _roster(self, request: AnalystRequest, possession_ids: set[str]) -> frozenset[str]:
        match_ids = {request.match_id} - {None} | {self.store.possession(p).match_id for p in possession_ids}
        names = []
        for match_id in match_ids:
            match = self.store.match(match_id)
            names += [p.name for p in match.players] + [t.name for t in match.teams]
        return name_words(names)

    def _offline(self, request: AnalystRequest) -> AnalystReply:
        text = load_language(request.language)["fallback"]["analyst_offline"]
        return AnalystReply(text=text, possession_ids=[], status="offline")

    async def answer(self, request: AnalystRequest) -> AnalystReply:
        if self.client is None or self.tools is None:
            return self._offline(request)
        messages = [
            Message(role="user", contents=[self._context(request)]),
            *(Message(role=turn.role, contents=[turn.text]) for turn in request.history),
            Message(role="user", contents=[request.question]),
        ]
        try:
            return await self._answer(request, messages)
        except Exception as error:  # LLM errors, the allowance, timeouts, the MCP connection: offline for now
            log.warning(json.dumps({"event": "analyst_error", "error": repr(error)[:300]}))
            return self._offline(request)

    def _check(self, request: AnalystRequest, draft: AnalystDraft) -> tuple[list[str], list[Rejection]]:
        known = self._existing(draft.possession_ids)
        roster = self._roster(request, known)
        rejections = verify_reply(draft.text, draft.possession_ids, known, roster, request.language)
        return [p for p in draft.possession_ids if p in known], rejections

    async def _answer(self, request: AnalystRequest, messages: list[Message]) -> AnalystReply:
        cited: list[str] = []
        rejections: list[Rejection] = []
        options = {"response_format": AnalystDraft, "temperature": 0.3, "max_tokens": 700}
        instructions = prompt("analyst.md")
        async with self.tools() as tools:
            agent = Agent(client=self.client, name="analyst", instructions=instructions, tools=[tools])
            for _ in range(2):
                with purpose("analyst"):
                    response = await asyncio.wait_for(agent.run(messages, options=options), TIMEOUT_S)
                try:
                    draft: AnalystDraft = response.value
                except (ValidationError, ValueError) as error:
                    rejections = [Rejection("malformed", f"not the requested JSON: {str(error)[:200]}")]
                else:
                    cited, rejections = self._check(request, draft)
                    if not rejections:
                        return AnalystReply(
                            text=draft.text, possession_ids=cited, status="verified", model=self.model
                        )
                retry = Message(role="user", contents=[feedback(rejections, "answer")])
                messages = [*messages, *response.messages, retry]
        log.info(json.dumps({"event": "analyst_fallback", "rejections": [r.code for r in rejections]}))
        fallback = load_language(request.language)["fallback"]
        text = fallback["analyst"] if cited else fallback["analyst_none"]
        return AnalystReply(text=text, possession_ids=cited, status="fallback", model=self.model)
