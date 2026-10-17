"""Results of LLM work (narratives, themes), keyed by a hash of everything that went into them: facts,
verdict, prompt version and model. A changed engine output or prompt makes a new key, so nothing stale is
served. Files live under CACHE_DIR/agents (gitignored); Phase 5 puts a Postgres table behind the same two
methods."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel


def cache_key(payload: dict) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class JsonCache:
    def __init__(self, root: Path | None):
        self.root = root
        self._memory: dict[str, str] = {}

    def _path(self, key: str) -> Path | None:
        return self.root / key[:2] / f"{key}.json" if self.root else None

    def get[M: BaseModel](self, key: str, model: type[M]) -> M | None:
        if key not in self._memory and (path := self._path(key)) and path.exists():
            self._memory[key] = path.read_text(encoding="utf-8")
        return model.model_validate_json(self._memory[key]) if key in self._memory else None

    def put(self, key: str, value: BaseModel) -> None:
        self._memory[key] = value.model_dump_json()
        if path := self._path(key):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._memory[key], encoding="utf-8")
