import re
import time
from collections import defaultdict

import numpy as np
import pytest

from filmroom.api.engine_store import EngineStore
from filmroom.data.catalog import Catalog
from filmroom.data.positions import team_of
from filmroom.data.textlog import PassComplete
from filmroom.engine.analyse import analyse_match, analyse_possession
from filmroom.engine.decisions import extract_decisions, intended_target
from filmroom.engine.possessions import PossessionSplitter, split_match
from filmroom.engine.training import fit_lomo, load_rows
from filmroom.engine.turning_point import load_params
from filmroom.eval.calibration import calibration_report, out_of_fold
from filmroom.eval.labels import load_labels
from filmroom.eval.scoring import DecisionPoint, label_decision_idx
from filmroom.style import load_lens, presets

pytestmark = pytest.mark.data


@pytest.fixture(scope="module")
def catalog(real_settings):
    return Catalog(real_settings)


@pytest.fixture(scope="module")
def labels(catalog, real_settings):
    return load_labels(real_settings.labels_path, "tuning", lambda m: catalog.load(m).clock)


@pytest.fixture(scope="module")
def possessions_by_match(catalog, labels):
    return {m: split_match(catalog.load(m)) for m in {label.match_id for label in labels}}


def _overlapping(label, possessions):
    same_team = [p for p in possessions if p.team == team_of(label.tp_pid)]
    return max(
        same_team, key=lambda p: min(p.end_frame, label.end_frame) - max(p.start_frame, label.start_frame)
    )


def test_owner_rows_and_events_are_in_frame_order(catalog):
    for info in catalog.matches():
        md = catalog.load(info.id)
        assert np.all(np.diff(md.possession_frames) > 0)
        assert all(a.frame <= b.frame for a, b in zip(md.events, md.events[1:], strict=False))


def test_splitter_reproduces_the_labelled_windows_within_a_second(labels, possessions_by_match):
    late_end = set()
    for label in labels:
        p = _overlapping(label, possessions_by_match[label.match_id])
        assert abs(p.start_frame - label.start_frame) <= 100, label.id
        if abs(p.end_frame - label.end_frame) > 100:
            late_end.add(label.id)
    # P20's window runs on through an opponent's clearance, which the splitter treats as a turnover.
    assert late_end == {"P20"}


def test_every_labelled_turning_point_maps_to_a_decision_and_final_rows_to_the_last(
    catalog, labels, possessions_by_match
):
    final_rows = []
    for label in labels:
        p = _overlapping(label, possessions_by_match[label.match_id])
        decisions = extract_decisions(catalog.load(label.match_id).until(p.close_frame), p)
        idx = label_decision_idx(label, [DecisionPoint(d.frame, d.pid) for d in decisions])
        assert idx is not None, label.id
        if label.final_action:
            final_rows.append(idx == len(decisions) - 1)
    assert len(final_rows) == 19 and all(final_rows)


def test_failed_pass_reconstruction_finds_the_receiver_of_most_completed_passes(catalog):
    hits = []
    for info in catalog.matches()[:6]:
        md = catalog.load(info.id)
        for e in md.events:
            if isinstance(e, PassComplete):
                hits.append(intended_target(md, e.start_frame, e.pid, e.frame)[0] == e.receiver)
    assert len(hits) > 1000
    assert sum(hits) / len(hits) >= 0.8


@pytest.fixture(scope="module")
def rows(catalog, real_settings):
    return load_rows(catalog, real_settings.cache_dir)


def test_every_usable_match_yields_pass_attempts(rows):
    assert len(rows) == 15
    assert sum(len(r.pass_y) for r in rows.values()) >= 5000


def test_pass_model_is_calibrated_out_of_fold(rows):
    report = calibration_report(*out_of_fold(rows, fit_lomo(rows)))
    assert report.ece <= 0.05
    assert report.brier < report.base_rate_brier
    low, medium, high = (report.bands[b].observed for b in ("low", "medium", "high"))
    assert low < medium < high


def test_live_analysis_equals_offline_for_every_possession_of_a_real_match(catalog, rows):
    match_id = "Match_2019_09_09_#001"
    md, models = catalog.load(match_id), fit_lomo(rows)[match_id]
    styles, params = presets(load_lens()), load_params()
    start = time.perf_counter()
    offline = [a.possession.model_dump() for a in analyse_match(md, models, styles, params)]
    assert time.perf_counter() - start < 30
    owners = dict(zip(md.possession_frames.tolist(), md.possession_pids.tolist(), strict=True))
    events_at = defaultdict(list)
    for e in md.events:
        events_at[e.frame].append(e)
    splitter, live = PossessionSplitter(), []
    frames = sorted(owners.keys() | events_at.keys())
    closes = [(f, splitter.step(f, owners.get(f), events_at.get(f, ()))) for f in frames]
    closes.append((frames[-1], splitter.flush(frames[-1])))
    for frame, closed in closes:
        for poss in closed:
            analysis = analyse_possession(md.until(frame), poss, models, styles, params)
            if analysis:
                live.append(analysis.possession.model_dump())
    assert len(live) > 200 and live == offline


def test_engine_store_output_is_valid_clean_and_cached(catalog, real_settings):
    slug = "2019_09_10_001"
    possessions = EngineStore.from_settings(real_settings).possessions(slug)
    start = time.perf_counter()
    restarted = EngineStore.from_settings(real_settings)
    assert restarted.possessions(slug) == possessions
    assert time.perf_counter() - start < 1.0
    flagged = [p for p in possessions if p.flagged]
    assert 0.05 < len(flagged) / len(possessions) < 0.4
    full = [restarted.possession(p.id) for p in flagged]
    blob = "\n".join(p.model_dump_json() for p in full)
    forbidden = catalog.identity.forbidden_names()
    assert not [n for n in forbidden if re.search(rf"\b{re.escape(n)}\b", blob)]
