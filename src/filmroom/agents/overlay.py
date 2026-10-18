"""The overlay feed: one event per flagged moment, shaped for a broadcast graphics system. Captions are the
fan narrative in every supported language with the slots filled, so every language carries the same numbers.
Narratives are peeked, never queued: the feed serves verified text where it is cached, and templates
otherwise."""

from filmroom.agents.facts import render, supported_languages
from filmroom.agents.layer import narration_for
from filmroom.agents.narratives import NarrativeService
from filmroom.contracts.models import Match, OverlayEvent, Possession


def overlay_events(
    possessions: list[Possession], match: Match, narratives: NarrativeService, style_id: str
) -> list[OverlayEvent]:
    """KeyError for an unknown preset."""
    events = []
    for possession in possessions:
        if not possession.flagged:
            continue
        captions = {}
        for language in supported_languages():
            narrative = narratives.peek(narration_for(possession, match, style_id, "fan", language))
            captions[language] = render(narrative.template, narrative.facts, language)
        verdict = possession.verdicts[style_id]
        events.append(
            OverlayEvent(
                t_ms=possession.decisions[verdict.decision_idx].t_ms,
                possession_id=possession.id,
                moment_type="turning_point",
                chosen_option_id=verdict.chosen_option_id,
                best_option_id=verdict.best_option_id,
                captions=captions,
            )
        )
    return sorted(events, key=lambda e: e.t_ms)
