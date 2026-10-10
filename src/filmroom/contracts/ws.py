"""WebSocket messages for live replay. Server messages are a union discriminated on `type`."""

from typing import Annotated, Literal

from pydantic import Field, RootModel

from filmroom.contracts.models import Contract, Narrative, PositionsChunk, PossessionSummary


class Clock(Contract):
    type: Literal["clock"] = "clock"
    t_ms: int
    speed: float


class PositionsMessage(Contract):
    type: Literal["positions"] = "positions"
    chunk: PositionsChunk


class PossessionFlagged(Contract):
    type: Literal["possession_flagged"] = "possession_flagged"
    summary: PossessionSummary
    narrative: Narrative


class NarrativeReady(Contract):
    type: Literal["narrative"] = "narrative"
    narrative: Narrative


class MatchEnd(Contract):
    type: Literal["match_end"] = "match_end"


class ErrorMessage(Contract):
    type: Literal["error"] = "error"
    message: str


class Control(Contract):
    type: Literal["control"] = "control"
    action: Literal["play", "pause", "seek", "speed"]
    value: float | None = None


class ServerMessage(
    RootModel[
        Annotated[
            Clock | PositionsMessage | PossessionFlagged | NarrativeReady | MatchEnd | ErrorMessage,
            Field(discriminator="type"),
        ]
    ]
):
    pass


class ClientMessage(RootModel[Control]):
    pass
