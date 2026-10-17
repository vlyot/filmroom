"""Support for the agent tests: engine output on the scripted synthetic match, and a chat client that replays
scripted responses so no test calls Mistral."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import cache

from agent_framework import (
    BaseChatClient,
    ChatMiddlewareLayer,
    ChatResponse,
    Content,
    FunctionInvocationLayer,
    Message,
)

from filmroom.api.engine_store import EngineStore
from filmroom.contracts.models import Match, Possession
from filmroom.engine.analyse import analyse_match
from filmroom.engine.assemble import match_view
from tests.engine_synth import SYNTH_MATCH, counter_attack
from tests.test_engine_analysis import FLAG_ALL, STYLES, constant_models

REFERENCE = STYLES[0]
STYLE_BY_ID = {s.id: s for s in STYLES}


@cache
def synth() -> tuple[Match, tuple[Possession, ...]]:
    """The synthetic match and its flagged possessions: a pass that a better pass beat, a dribble out of play,
    and a shot that only the reference preset would have swapped for a pass."""
    md = counter_attack().build()
    analyses = analyse_match(md, constant_models(), STYLES, FLAG_ALL)
    return match_view(md), tuple(a.possession for a in analyses if a.possession.flagged)


def synth_store() -> EngineStore:
    """An engine store over the synthetic match, every possession flagged."""
    md = counter_attack().build()
    return EngineStore(
        load=lambda match_id: md,
        match_ids=[SYNTH_MATCH],
        models=lambda: {SYNTH_MATCH: constant_models()},
        styles=STYLES,
        params=FLAG_ALL,
    )


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict = field(default_factory=dict)


Reply = str | dict | ToolCall | Exception | Callable[[Sequence[Message]], "Reply"]


class ScriptedChatClient(FunctionInvocationLayer, ChatMiddlewareLayer, BaseChatClient):
    """Answers each model call with the next scripted reply: text, a dict (sent as JSON, for structured
    output), a tool call, an exception to raise, or a function of the messages. It has the same layers as
    MistralChatClient, so tool loops and middleware run as they do against Mistral."""

    def __init__(self, replies: Sequence[Reply], **kwargs):
        super().__init__(**kwargs)
        self.replies = list(replies)
        self.requests: list[list[Message]] = []

    def _inner_get_response(self, *, messages, options, stream=False, **kwargs):
        async def respond() -> ChatResponse:
            self.requests.append(list(messages))
            reply = self.replies.pop(0)
            if callable(reply) and not isinstance(reply, ToolCall):
                reply = reply(messages)
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, ToolCall):
                content = Content.from_function_call(
                    call_id=f"call_{len(self.requests)}", name=reply.name, arguments=reply.arguments
                )
            else:
                content = Content.from_text(json.dumps(reply) if isinstance(reply, dict) else reply)
            return ChatResponse(
                messages=[Message(role="assistant", contents=[content])],
                usage_details={"input_token_count": 300, "output_token_count": 40},
                model="scripted",
                response_format=options.get("response_format"),
            )

        return respond()
