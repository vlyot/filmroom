"""Fictional identities. The game's names parody real players and clubs, so every name is replaced here.

The same original name gets the same fictional name and key in every match, so skill profiles can follow a
player across matches. Teams are identified by their roster, so the same squad keeps the same fictional club.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from filmroom.data.textlog import RosterEntry

NAMES = json.loads(Path(__file__).with_name("names.json").read_text(encoding="utf-8"))


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assign(keys: list[str], pool: list[str], avoid: set[str]) -> dict[str, str]:
    taken: set[str] = set()
    assigned = {}
    for key in sorted(keys):
        start = int(_digest(key)[:12], 16)
        for step in range(len(pool)):
            candidate = pool[(start + step) % len(pool)]
            if candidate not in taken and candidate not in avoid:
                break
        else:
            raise ValueError(f"name pool of {len(pool)} exhausted")
        taken.add(candidate)
        assigned[key] = candidate
    return assigned


@dataclass(frozen=True)
class Identity:
    key: str
    name: str


MIRROR = " (mirror)"


@dataclass(frozen=True)
class IdentityMap:
    players: dict[str, Identity]  # source name -> fictional identity
    teams: dict[tuple[str, int], Identity]  # (match id, side) -> fictional club
    mirror_matches: frozenset[str]  # matches where one squad plays itself

    def player(self, match_id: str, side: int, original_name: str) -> Identity:
        return self.players[_source_name(match_id, side, original_name, self.mirror_matches)]

    def team(self, match_id: str, side: int) -> Identity:
        return self.teams[(match_id, side)]

    def forbidden_names(self) -> set[str]:
        return {name.removesuffix(MIRROR) for name in self.players}


def _source_name(match_id: str, side: int, name: str, mirror_matches: frozenset[str]) -> str:
    return name + MIRROR if side == 1 and match_id in mirror_matches else name


def team_fingerprint(match_id: str, side: int, roster: list[RosterEntry]) -> str:
    names = sorted(r.name for r in roster if r.team == side)
    return "|".join(names) if names else f"unknown:{match_id}:{side}"


def build_identity(rosters: Mapping[str, list[RosterEntry]]) -> IdentityMap:
    fingerprints = {
        (match_id, side): team_fingerprint(match_id, side, roster)
        for match_id, roster in rosters.items()
        for side in (0, 1)
    }
    mirror = frozenset(m for m in rosters if fingerprints[(m, 0)] == fingerprints[(m, 1)])
    for match_id in mirror:
        fingerprints[(match_id, 1)] += MIRROR

    originals = sorted(
        {_source_name(m, r.team, r.name, mirror) for m, roster in rosters.items() for r in roster}
    )
    original_words = {word.lower() for o in originals for word in o.removesuffix(MIRROR).split()}
    pool = [
        f"{first} {last}"
        for first in NAMES["first"]
        for last in NAMES["last"]
        if first.lower() not in original_words and last.lower() not in original_words
    ]
    names = _assign(originals, pool, avoid=set())
    players = {o: Identity("pl_" + _digest(o)[:10], names[o]) for o in originals}

    clubs = _assign(sorted(set(fingerprints.values())), NAMES["clubs"], avoid=set())
    teams = {k: Identity("tm_" + _digest(fp)[:10], clubs[fp]) for k, fp in fingerprints.items()}
    return IdentityMap(players, teams, mirror)
