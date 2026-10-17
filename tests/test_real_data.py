import re
import time

import numpy as np
import pytest

from filmroom.agents.facts import supported_languages
from filmroom.agents.layer import AgentLayer
from filmroom.api.bundle import export_bundle
from filmroom.api.store import FixtureStore
from filmroom.contracts.models import template_slots
from filmroom.data.catalog import Catalog
from filmroom.eval.cli import FixtureDecisionSource, evaluate
from filmroom.eval.labels import load_labels
from filmroom.style import load_lens, presets_by_id
from tests.conftest import REPO

pytestmark = pytest.mark.data

NO_EVENTS = {"Match_2019_09_13_#001", "Match_2019_09_15_#003"}


@pytest.fixture(scope="module")
def catalog(real_settings):
    return Catalog(real_settings)


@pytest.fixture(scope="module")
def fixture_store():
    store = FixtureStore(REPO / "fixtures")
    if not (REPO / "fixtures" / "possessions").is_dir():
        pytest.skip("local fixtures not built; run scripts/build_fixtures.py")
    return store


def test_all_17_matches_load_and_two_have_no_usable_events(catalog):
    loaded = {m.id: catalog.load(m.id) for m in catalog.matches()}
    assert len(loaded) == 17
    assert {mid for mid, md in loaded.items() if not md.has_events} == NO_EVENTS
    assert all(not md.unparsed for mid, md in loaded.items() if mid not in NO_EVENTS)


def test_positions_run_at_about_100_hz_and_match_frame_times(catalog):
    md = catalog.load("Match_2019_09_09_#001")
    hz = len(md.track.frames) / (md.clock.ms[-1] / 1000)
    assert 99 < hz < 101
    assert np.array_equal(md.track.frames, md.clock.frames)
    assert md.track.missing == 0


def test_cached_load_is_under_one_second(catalog):
    catalog.load("Match_2019_09_10_#001")
    start = time.perf_counter()
    catalog.load("Match_2019_09_10_#001")
    assert time.perf_counter() - start < 1.0


def test_no_original_name_reaches_loaded_players(catalog):
    forbidden = catalog.identity.forbidden_names()
    for m in catalog.matches():
        assert not {p.name for p in catalog.load(m.id).players} & forbidden


def test_all_tuning_turning_points_fall_inside_their_windows(catalog, real_settings):
    labels = load_labels(real_settings.labels_path, "tuning", lambda m: catalog.load(m).clock)
    assert len(labels) == 25
    assert all(r.start_frame - 100 <= r.tp_frame <= r.end_frame + 100 for r in labels)


def test_built_fixtures_are_valid_and_their_narratives_resolve(fixture_store):
    fixtures = fixture_store.all_fixtures()
    assert len(fixtures) == 4
    agents = AgentLayer.offline(fixture_store)
    for f in fixtures:
        for style in presets_by_id(load_lens()):
            for language in supported_languages():
                request = agents.narration(f.possession.id, style, "coach", language)
                assert template_slots(request.template().template) <= set(request.facts)
    assert any(v.flip_reason for f in fixtures for v in f.possession.verdicts.values())


def test_no_original_name_appears_in_fixtures_or_bundle(catalog, fixture_store, tmp_path):
    export_bundle(fixture_store, tmp_path / "bundle", public=False)
    texts = [p.read_text(encoding="utf-8") for p in (REPO / "fixtures").rglob("*.json")]
    texts += [p.read_text(encoding="utf-8") for p in (tmp_path / "bundle").rglob("*.json")]
    blob = "\n".join(texts)
    leaks = [n for n in catalog.identity.forbidden_names() if re.search(rf"\b{re.escape(n)}\b", blob)]
    assert leaks == []


def test_eval_runs_end_to_end_on_fixtures(catalog, fixture_store, real_settings):
    labels = load_labels(real_settings.labels_path, "tuning", lambda m: catalog.load(m).clock)
    detector, final_action, random = evaluate(labels, FixtureDecisionSource(fixture_store))
    assert detector.n == final_action.n == random.n == 4
    assert 0 < random.exact < random.near <= 4
