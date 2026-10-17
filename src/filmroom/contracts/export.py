"""Write contracts/schema.json (every model) and contracts/openapi.json. CI fails if they drift from the code.

Usage: uv run python -m filmroom.contracts.export
"""

import json
from pathlib import Path

from pydantic.json_schema import GenerateJsonSchema, models_json_schema

from filmroom.api.app import create_app
from filmroom.api.store import FixtureStore
from filmroom.contracts.models import (
    CONTRACT_VERSION,
    AnalystReply,
    AnalystRequest,
    BundleManifest,
    Health,
    Match,
    MatchSummary,
    Narrative,
    OverlayEvent,
    PositionsChunk,
    Possession,
    PossessionSummary,
    SessionPack,
    StyleConfig,
    StyleLens,
)
from filmroom.contracts.ws import ClientMessage, ServerMessage

MODELS = [
    Health,
    MatchSummary,
    Match,
    PossessionSummary,
    Possession,
    PositionsChunk,
    StyleConfig,
    StyleLens,
    Narrative,
    AnalystRequest,
    AnalystReply,
    SessionPack,
    OverlayEvent,
    BundleManifest,
    ServerMessage,
    ClientMessage,
]
OUT_DIR = Path("contracts")


class ContractSchema(GenerateJsonSchema):
    """Schema shaped for TypeScript generation: no per-field titles (they become noise type aliases) and
    fixed-length tuples as items/minItems/maxItems, which json-schema-to-typescript turns into tuple types."""

    def field_title_should_be_set(self, schema) -> bool:
        return False

    def tuple_schema(self, schema):
        js = super().tuple_schema(schema)
        items = js.pop("prefixItems", None)
        if items:
            js["items"] = items[0] if all(i == items[0] for i in items) else items
            js["minItems"] = js["maxItems"] = len(items)
        return js


def schema() -> dict:
    _, top = models_json_schema(
        [(m, "serialization") for m in MODELS], title="FilmRoom contracts", schema_generator=ContractSchema
    )
    return {"x-contract-version": CONTRACT_VERSION, **top}


def openapi() -> dict:
    return create_app(FixtureStore(Path("fixtures")), cors_origins=[]).openapi()


def render(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def export_all(out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "schema.json").write_text(render(schema()), encoding="utf-8")
    (out_dir / "openapi.json").write_text(render(openapi()), encoding="utf-8")


if __name__ == "__main__":
    export_all()
