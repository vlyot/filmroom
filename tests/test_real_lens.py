import pytest

from filmroom.data.catalog import Catalog
from filmroom.engine.analyse import analyse_match
from filmroom.engine.training import fit_lomo, load_rows
from filmroom.engine.turning_point import load_params
from filmroom.eval.agreement import alternatives_agreement, build_cases
from filmroom.eval.calibration import calibration_report, shot_out_of_fold
from filmroom.eval.labels import load_labels
from filmroom.eval.lens import attribution, direction_violations, disagreement, flagged_turning_points
from filmroom.style import load_lens, presets

pytestmark = pytest.mark.data
STYLES = presets(load_lens())


@pytest.fixture(scope="module")
def catalog(real_settings):
    return Catalog(real_settings)


@pytest.fixture(scope="module")
def rows(catalog, real_settings):
    return load_rows(catalog, real_settings.cache_dir)


@pytest.fixture(scope="module")
def models(rows):
    return fit_lomo(rows)


@pytest.fixture(scope="module")
def analyses(catalog, rows, models):
    params = load_params()
    return {m: analyse_match(catalog.load(m), models[m], STYLES, params) for m in rows}


@pytest.fixture(scope="module")
def flagged(analyses):
    return flagged_turning_points([a for match in analyses.values() for a in match], load_params())


def test_every_flip_between_presets_traces_to_a_factor_both_cards_name(flagged):
    result = attribution(flagged, STYLES)
    assert result.flips > 0 and result.failures == []


def test_every_pair_of_presets_disagrees_somewhere_and_the_contrasting_pair_sits_in_the_band(flagged):
    pairs = disagreement(flagged, STYLES)
    assert min(p.disagree for p in pairs) > 0
    [headline] = [p for p in pairs if {p.a, p.b} == {"possession-high-press", "counter-low-block"}]
    assert headline.in_band, headline.rate


def test_slider_sweeps_on_real_decisions_move_rankings_only_the_stated_way(flagged):
    assert set(direction_violations(flagged, load_lens(), STYLES).values()) == {0}


def test_xg_beats_the_scoring_rate_out_of_fold(rows, models):
    report = calibration_report(*shot_out_of_fold(rows, models))
    assert report.n > 300 and report.brier < report.base_rate_brier and report.ece <= 0.08


def test_what_was_on_instead_still_finds_twelve_of_twenty_two(catalog, real_settings, analyses):
    labels = load_labels(real_settings.labels_path, "tuning", lambda m: catalog.load(m).clock)
    result = alternatives_agreement(build_cases(labels, analyses))
    assert (result.n, result.top_k) == (22, 12)
