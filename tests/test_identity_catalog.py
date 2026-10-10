import numpy as np
import pytest

from filmroom.config import Settings
from filmroom.data import catalog as catalog_module
from filmroom.data.catalog import Catalog
from filmroom.data.identity import build_identity
from filmroom.data.textlog import RosterEntry
from tests.conftest import MINI_MATCH


def _squad(prefix: str, team: int) -> list[RosterEntry]:
    base = 0 if team == 0 else 18
    return [
        RosterEntry(
            base + i, base + i + (128 if team else 0), team, f"{prefix}{i}", "GK" if i == 0 else "OUT"
        )
        for i in range(11)
    ]


ROSTERS = {
    "A": _squad("Red", 0) + _squad("Blue", 1),
    "B": _squad("Red", 0) + _squad("Green", 1),
    "M": _squad("Gold", 0) + _squad("Gold", 1),
}


def test_same_original_name_gets_same_fictional_name_across_matches():
    ids = build_identity(ROSTERS)
    assert ids.player("A", 0, "Red3") == ids.player("B", 0, "Red3")
    assert ids.team("A", 0) == ids.team("B", 0)
    assert ids.team("A", 1) != ids.team("B", 1)


def test_fictional_names_are_unique_and_never_original():
    ids = build_identity(ROSTERS)
    fictional = [p.name for p in ids.players.values()]
    assert len(set(fictional)) == len(fictional)
    assert not set(fictional) & ids.forbidden_names()


def test_mirror_match_gives_each_side_its_own_players_and_club():
    ids = build_identity(ROSTERS)
    assert ids.mirror_matches == {"M"}
    assert ids.player("M", 0, "Gold2") != ids.player("M", 1, "Gold2")
    assert ids.team("M", 0) != ids.team("M", 1)
    assert "Gold2" in ids.forbidden_names()


def test_catalog_loads_match_with_fictional_identities(mini_settings):
    cat = Catalog(mini_settings)
    assert [m.id for m in cat.matches()] == [MINI_MATCH]
    md = cat.load(MINI_MATCH)
    assert len(md.players) == 22
    assert not {p.name for p in md.players} & cat.identity.forbidden_names()
    keepers = [p for p in md.players if p.role == "GK"]
    assert [(p.pid, p.shirt) for p in keepers] == [(0, 1), (146, 1)]
    assert [t.attacks_towards_x for t in md.teams] == [110.0, 0.0]
    assert md.info.video.name == "Recording.MKV"
    assert not md.has_events  # 14 events is below the broken-log threshold


def test_catalog_second_load_comes_from_cache(mini_settings, monkeypatch):
    cat = Catalog(mini_settings)
    first = cat.load(MINI_MATCH)

    def fail(*_):
        raise AssertionError("parsed again instead of using the cache")

    monkeypatch.setattr(catalog_module, "parse_positions", fail)
    monkeypatch.setattr(catalog_module, "parse_textlog", fail)
    second = cat.load(MINI_MATCH)
    np.testing.assert_array_equal(second.track.xy, first.track.xy)
    assert second.events == first.events
    assert second.players == first.players


def test_catalog_requires_data_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        Catalog(Settings(_env_file=None, data_dir=tmp_path / "missing"))
