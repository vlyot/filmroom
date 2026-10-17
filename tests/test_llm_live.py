"""Against the live Mistral API: a handful of calls (under a cent). Skipped unless RUN_LLM_TESTS=1."""

import asyncio

import pytest

from filmroom.agents.analyst import Analyst
from filmroom.agents.llm import LlmBudget, make_chat_client
from filmroom.agents.narrator import NarrationRequest, Narrator
from filmroom.config import Settings
from filmroom.contracts.models import AnalystRequest
from tests.agent_fakes import REFERENCE, STYLE_BY_ID, synth, synth_store
from tests.test_analyst import memory_tools

pytestmark = pytest.mark.llm


@pytest.fixture
def client():
    """A fresh client per test: its connection pool belongs to the event loop of one asyncio.run."""
    settings = Settings()
    return make_chat_client(settings, LlmBudget(settings.llm_daily_token_limit)), settings.mistral_chat_model


@pytest.mark.parametrize(("language", "style_id"), [("en", REFERENCE.id), ("es", "counter-low-block")])
def test_the_narrator_writes_a_verified_narrative(client, language, style_id):
    llm, model = client
    match, possessions = synth()
    request = NarrationRequest(possessions[-1], match, STYLE_BY_ID[style_id], REFERENCE, "coach", language)
    result = asyncio.run(Narrator(llm, model).generate(request))
    assert result.narrative.status == "verified", result.rejections


def test_the_analyst_answers_from_the_engine_tools(client):
    llm, model = client
    request = AnalystRequest(question="Which moment was the most severe, and why?", match_id="2000_01_01_009")
    reply = asyncio.run(Analyst(llm, model, synth_store(), memory_tools()).answer(request))
    assert reply.status in ("verified", "fallback")
    assert reply.status == "fallback" or reply.possession_ids
