import numpy as np

from filmroom.engine.geometry import (
    CAP_M,
    Snapshot,
    attacking,
    interceptors,
    lane_clearance,
    snapshot,
    space_share,
    voronoi_control,
)
from filmroom.engine.possessions import split_match
from filmroom.engine.xt import GRID, danger_curve, xt
from tests.engine_synth import TEAM1, SynthMatch, counter_attack


def _snap(attackers, defenders):
    att = np.asarray(attackers, dtype=float)
    return Snapshot(0, 0, att[0], np.arange(len(att)), att, np.asarray(defenders, dtype=float))


def test_team_1_is_rotated_to_attack_towards_x_110():
    md = SynthMatch().place(151, (20.0, 10.0)).hold(151, 5).build()
    snap = snapshot(md, 0, team=1)
    assert sorted(snap.att_pids.tolist()) == TEAM1
    assert np.allclose(snap.position(151), (90.0, 62.0))
    assert np.allclose(snap.ball, (90.0, 62.0))


def test_lane_clearance_counts_only_defenders_between_passer_and_target():
    origin, target = np.asarray((50.0, 36.0)), np.asarray((70.0, 36.0))
    assert lane_clearance(_snap([origin], [(45, 36), (60, 40)]), origin, target) == 4.0
    assert lane_clearance(_snap([origin], [(45, 36), (75, 36)]), origin, target) == CAP_M
    assert interceptors(_snap([origin], [(55, 37), (60, 39), (65, 35)]), origin, target) == 2


def test_voronoi_control_gives_each_cell_to_the_nearest_player():
    snap = _snap([(30, 36)], [(80, 36)])
    control = voronoi_control(snap)
    assert control.shape == (36, 55)
    assert control[:, :27].all() and not control[:, 28:].any()
    assert space_share(control, np.asarray((30.0, 36.0))) == 1.0
    assert space_share(control, np.asarray((80.0, 36.0))) == 0.0


def test_xt_rises_third_by_third_towards_goal_and_matches_the_source_grid_at_its_corners():
    centre = xt(np.column_stack([np.linspace(1, 109, 12), np.full(12, 36.0)]))
    own, mid, final = centre[:4].mean(), centre[4:8].mean(), centre[8:].mean()
    assert own < mid < final and centre[-1] == GRID[4, 11] == GRID.max()
    assert xt(np.asarray((0.0, 0.0))) == GRID[0, 0] and xt(np.asarray((110.0, 72.0))) == GRID[7, 11]


def test_danger_curve_samples_the_ball_at_2_hz_from_the_attacking_side():
    md = counter_attack().build()
    first, second, *_ = split_match(md)
    curve = danger_curve(md, first)
    assert [p.t_ms for p in curve[:3]] == [0, 500, 1000]
    assert curve[0].xt == round(float(xt(np.asarray(md.track.xy[0, 0]))), 4)
    team1_ball = attacking(md.track.xy[second.start_frame, 0], team=1)
    assert danger_curve(md, second)[0].xt == round(float(xt(team1_ball)), 4)
