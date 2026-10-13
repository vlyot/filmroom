import numpy as np
import pytest

from filmroom.engine.geometry import Snapshot, voronoi_control
from filmroom.engine.press import counter_press, rest_defence


def _snapshot(att: list[tuple[float, float]], dfn: list[tuple[float, float]]) -> Snapshot:
    att_xy = np.asarray(att, dtype=float)
    return Snapshot(0, 0, att_xy[0], np.arange(1, len(att) + 1), att_xy, np.asarray(dfn, dtype=float))


def test_counter_press_counts_teammates_within_ten_metres_capped_at_three():
    loss = np.asarray((60.0, 36.0))
    snap = _snapshot([(55, 36), (60, 44), (71, 36), (75, 36)], [(90, 36)])
    assert counter_press(snap, loss) == pytest.approx(2 / 3)
    crowded = _snapshot([(55, 36), (60, 44), (65, 36), (60, 30), (62, 38)], [(90, 36)])
    assert counter_press(crowded, loss) == 1.0
    assert counter_press(_snapshot([(20, 10)], [(90, 36)]), loss) == 0.0


def test_rest_defence_is_the_share_of_the_space_behind_the_loss_point_we_control():
    loss = np.asarray((60.0, 36.0))
    covered = _snapshot([(30, 20), (30, 52), (60, 36)], [(100, 36)])
    exposed = _snapshot([(100, 36)], [(30, 20), (30, 52), (60, 36)])
    assert rest_defence(voronoi_control(covered), loss) == 1.0
    assert rest_defence(voronoi_control(exposed), loss) == 0.0
    mixed = _snapshot([(30, 20), (100, 36)], [(30, 52)])
    assert 0.0 < rest_defence(voronoi_control(mixed), loss) < 1.0


def test_rest_defence_at_the_own_goal_line_still_reads_the_first_column():
    snap = _snapshot([(1, 36)], [(100, 36)])
    assert rest_defence(voronoi_control(snap), np.asarray((0.0, 36.0))) == 1.0
