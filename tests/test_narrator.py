import asyncio

import pytest
from agent_framework.exceptions import ChatClientException

from filmroom.agents.narrator import NarrationRequest, Narrator, moment_message
from tests.agent_fakes import REFERENCE, STYLE_BY_ID, ScriptedChatClient, synth


def _request(style_id: str = REFERENCE.id, language: str = "en") -> NarrationRequest:
    match, possessions = synth()
    return NarrationRequest(possessions[0], match, STYLE_BY_ID[style_id], REFERENCE, "coach", language)


def _clean_draft(request: NarrationRequest) -> dict:
    template = request.template()
    return {"text": template.template, "claims": [c.model_dump() for c in template.claims]}


def _generate(request: NarrationRequest, replies: list):
    client = ScriptedChatClient(replies)
    result = asyncio.run(Narrator(client, "mistral-small-2603").generate(request))
    return result, client


def test_returns_a_verified_narrative_from_a_clean_first_draft():
    request = _request()
    best = request.possession.verdicts[REFERENCE.id].best_option_id
    draft = {
        "text": "Under {style.name}, {tp.player} should have picked {best.action} at {tp.time}.",
        "claims": [{"type": "better_option", "ref": best}],
    }
    result, client = _generate(request, [draft])
    assert result.narrative.status == "verified" and result.rejections == []
    assert result.narrative.template == draft["text"] and result.narrative.facts == request.facts
    assert result.narrative.model == "mistral-small-2603" and len(client.requests) == 1


def test_retries_once_with_the_rejections_then_succeeds():
    request = _request()
    leaked = _clean_draft(request) | {"text": "At {tp.time} he had 3 options."}
    result, client = _generate(request, [leaked, _clean_draft(request)])
    assert result.narrative.status == "verified"
    retry = client.requests[1][-1].text
    assert "verifier rejected" in retry and "digit" in retry


def test_falls_back_to_the_template_after_two_rejections():
    request = _request()
    wrong = _clean_draft(request) | {"claims": []}
    result, client = _generate(request, [wrong, wrong])
    assert result.narrative.status == "failed"
    assert result.narrative.template == request.template().template
    assert [r.code for r in result.rejections] == ["claim_missing"] and len(client.requests) == 2


def test_treats_output_that_is_not_the_requested_json_as_a_rejection():
    request = _request()
    result, client = _generate(request, ["Sure! Here is a narrative.", _clean_draft(request)])
    assert result.narrative.status == "verified"
    assert "malformed" in client.requests[1][-1].text


def test_lets_llm_errors_propagate_so_nothing_is_cached():
    with pytest.raises(ChatClientException):
        _generate(_request(), [ChatClientException("429 rate limited")])


def test_tells_the_narrator_only_about_slots_it_may_use():
    message = moment_message(_request("direct-mid-block", "es"))
    assert "{best.action} (phrase)" in message and "{flip.factor} (phrase)" in message
    assert "alt." not in message and "decisions.after_tp" not in message
    assert "Spanish" in message and "Direct" in message
