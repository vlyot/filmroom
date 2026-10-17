import asyncio
from contextlib import asynccontextmanager

from agent_framework import MCPStreamableHTTPTool
from agent_framework.exceptions import ChatClientException
from mcp.shared.memory import create_connected_server_and_client_session

from filmroom.agents.analyst import Analyst
from filmroom.agents.mcp_server import build_mcp
from filmroom.agents.tools import EngineTools
from filmroom.contracts.models import AnalystRequest, ChatTurn
from tests.agent_fakes import ScriptedChatClient, ToolCall, synth_store

SLUG = "2000_01_01_009"
STORE = synth_store()


def memory_tools():
    """The engine's MCP server over an in-memory session: the full protocol, no network."""
    mcp = build_mcp(EngineTools(STORE))

    @asynccontextmanager
    async def connect():
        async with create_connected_server_and_client_session(mcp._mcp_server) as session:
            tool = MCPStreamableHTTPTool("filmroom_engine", "memory://", session=session, load_prompts=False)
            async with tool:
                yield tool

    return connect


def _ask(replies, question="Where did we lose the ball?", history=(), language="en"):
    client = ScriptedChatClient(replies)
    analyst = Analyst(client, "scripted-model", STORE, memory_tools())
    request = AnalystRequest(question=question, history=list(history), match_id=SLUG, language=language)
    return asyncio.run(analyst.answer(request)), client


def _flagged_ids() -> list[str]:
    return [p.id for p in STORE.match_possessions(SLUG) if p.flagged]


def test_answers_through_an_engine_tool_called_over_mcp():
    first = _flagged_ids()[0]
    answer = {"text": "The move broke down in midfield after a forced pass.", "possession_ids": [first]}
    reply, client = _ask([ToolCall("list_flagged_moments", {"match_id": SLUG, "limit": 3}), answer])
    assert reply.status == "verified" and reply.possession_ids == [first] and reply.model == "scripted-model"
    tool_results = [c.result for m in client.requests[1] for c in m.contents if c.type == "function_result"]
    assert tool_results and first in str(tool_results[0])


def test_passes_the_match_the_styles_and_the_history_to_the_agent():
    answer = {"text": "Nothing stood out.", "possession_ids": []}
    history = [ChatTurn(role="user", text="Hi"), ChatTurn(role="assistant", text="Hello.")]
    _, client = _ask([answer], history=history, language="es")
    sent = "\n".join(m.text for m in client.requests[0])
    assert "Alpha v Beta" in sent and "possession-high-press" in sent and "Spanish" in sent
    assert "Hello." in sent and "Where did we lose the ball?" in sent


def test_retries_a_rejected_answer_with_the_reasons():
    first = _flagged_ids()[0]
    leaked = {"text": "He lost it 3 times.", "possession_ids": [first]}
    clean = {"text": "He kept forcing it.", "possession_ids": [first]}
    reply, client = _ask([leaked, clean])
    assert reply.status == "verified"
    assert "digit" in client.requests[1][-1].text


def test_falls_back_to_the_cited_moments_after_two_rejections():
    first = _flagged_ids()[0]
    replies = [
        {"text": "Twice he lost it.", "possession_ids": [first, "nope-1"]},
        {"text": "Messi would have scored.", "possession_ids": [first]},
    ]
    reply, _ = _ask(replies)
    assert reply.status == "fallback" and reply.possession_ids == [first]
    assert reply.text.startswith("I couldn't put that into words")


def test_reports_offline_without_a_client_or_when_the_llm_fails():
    request = AnalystRequest(question="Anything?", match_id=SLUG, language="es")
    offline = asyncio.run(Analyst(None, "m", STORE, memory_tools()).answer(request))
    assert offline.status == "offline" and offline.possession_ids == []
    failed, _ = _ask([ChatClientException("402 allowance used up")])
    assert failed.status == "offline" and failed.text == "The live analyst is offline right now."
