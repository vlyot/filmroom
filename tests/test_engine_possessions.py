import numpy as np

from filmroom.engine.possessions import PossessionSplitter, split_match
from tests.engine_synth import SynthMatch, counter_attack


def _summary(possessions):
    return [(p.team, p.start_frame, p.end_frame, p.close_frame, p.end_reason) for p in possessions]


def test_possessions_open_on_first_owner_row_and_close_on_first_opponent_row():
    possessions = split_match(counter_attack().build())
    assert _summary(possessions) == [
        (0, 0, 229, 260, "turnover"),
        (1, 260, 399, 400, "ball_out"),
        (0, 450, 579, 610, "match_end"),
    ]
    assert [(s.pid, s.first_frame, s.last_frame) for s in possessions[0].spells] == [
        (6, 0, 39),
        (9, 90, 149),
        (10, 200, 229),
    ]


def test_goal_and_foul_close_the_open_possession():
    goal = SynthMatch().hold(9, 20).shot(9, outcome="goal").idle(50).hold(151, 20).build()
    assert [p.end_reason for p in split_match(goal)] == ["goal", "match_end"]
    foul = SynthMatch().hold(9, 20).foul(151).hold(9, 20).build()
    assert [(p.team, p.end_reason) for p in split_match(foul)] == [(0, "foul"), (0, "match_end")]


def test_a_shot_does_not_close_the_possession():
    md = SynthMatch().hold(9, 20).shot(9, outcome="saved").hold(10, 20).build()
    [possession] = split_match(md)
    assert (possession.start_frame, possession.end_frame) == (0, 69)


def test_split_match_equals_a_frame_by_frame_feed():
    md = counter_attack().build()
    splitter, fed = PossessionSplitter(), []
    owners = dict(zip(md.possession_frames.tolist(), md.possession_pids.tolist(), strict=True))
    last = max(int(md.track.frames[-1]), md.events[-1].frame)
    for frame in range(last + 1):
        fed += splitter.step(frame, owners.get(frame), [e for e in md.events if e.frame == frame])
    fed += splitter.flush(last)
    assert _summary(fed) == _summary(split_match(md))


def test_until_hides_everything_logged_after_the_frame():
    md = counter_attack().build()
    view = md.until(260)
    assert view.track.frames[-1] == 260 and view.clock.frames[-1] == 260
    assert view.possession_frames[-1] == 260
    assert max(e.frame for e in view.events) <= 260
    assert np.shares_memory(view.track.xy, md.track.xy)
