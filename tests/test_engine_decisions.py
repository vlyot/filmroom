from filmroom.data.textlog import Kick, PassComplete, PassStart, Tackle
from filmroom.engine.decisions import extract_decisions, possession_outcome, tackle_winner
from filmroom.engine.possessions import split_match
from tests.engine_synth import SynthMatch, counter_attack


def _decisions(md):
    return [(p, extract_decisions(md.until(p.close_frame), p)) for p in split_match(md)]


def test_logged_lines_for_one_pass_merge_into_one_decision():
    (_, decisions), *_ = _decisions(counter_attack().build())
    assert [(d.frame, d.pid, d.kind, d.completed, d.target_pid) for d in decisions] == [
        (40, 6, "pass", True, 9),
        (150, 9, "pass", True, 10),
        (230, 10, "pass", False, 9),
    ]


def test_a_completion_with_no_start_or_kick_line_is_still_a_decision():
    md = SynthMatch().hold(6, 20).pass_to(6, 9, logged_start=False).hold(9, 20).build()
    md.events = [e for e in md.events if not isinstance(e, Kick | PassStart)]
    [(_, [decision])] = _decisions(md)
    assert (decision.frame, decision.kind, decision.completed, decision.target_pid) == (20, "pass", True, 9)


def test_failed_pass_target_is_the_teammate_on_the_ball_path():
    (_, decisions), *_ = _decisions(counter_attack().build())
    assert decisions[-1].target_pid == 9


def test_a_final_dribble_is_added_only_when_the_carrier_never_released_the_ball():
    md = SynthMatch().hold(6, 20).pass_to(6, 9).hold(9, 80, to=(70, 30)).tackle(9, 151).hold(151, 20).build()
    (_, decisions), _ = _decisions(md)
    assert [(d.frame, d.pid, d.kind) for d in decisions] == [(20, 6, "pass"), (99, 9, "carry")]
    (_, released), *_ = _decisions(counter_attack().build())
    assert all(d.kind == "pass" for d in released)


def test_tackle_winner_comes_from_the_next_owner_with_the_log_as_fallback():
    md = SynthMatch().hold(9, 20).tackle(9, 151, outcome="lose").hold(151, 20).build()
    assert tackle_winner(md, next(e for e in md.events if isinstance(e, Tackle))) == 1
    for outcome, winner in (("win", 1), ("lose", 0)):
        md = SynthMatch().hold(9, 20).tackle(9, 151, outcome=outcome).idle(300).build()
        assert tackle_winner(md, next(e for e in md.events if isinstance(e, Tackle))) == winner


def _outcomes(md):
    return [possession_outcome(md.until(p.close_frame), p, d) for p, d in _decisions(md)]


def test_possession_outcomes_follow_their_precedence():
    assert _outcomes(counter_attack().build())[:2] == [("lost_pass", "mid"), ("out", "mid")]
    goal = SynthMatch().hold(9, 20).shot(9, outcome="goal").idle(50).hold(151, 20).build()
    assert _outcomes(goal)[0][0] == "goal"
    shot = SynthMatch().hold(9, 20).shot(9).hold(151, 20).build()
    assert _outcomes(shot)[0][0] == "shot"
    foul = SynthMatch().hold(9, 20).foul(151).build()
    assert _outcomes(foul)[0][0] == "stoppage"
    tackled = SynthMatch().hold(6, 20).pass_to(6, 9).hold(9, 30).tackle(9, 151).hold(151, 20).build()
    assert _outcomes(tackled)[0][0] == "lost_tackle"


def test_a_pass_completed_to_the_passer_is_a_dribble_that_kept_the_ball():
    m = SynthMatch().hold(6, 20)
    m.events.append(PassComplete(30, 20, 6, 6, False))
    md = m.hold(6, 20).pass_to(6, 9).hold(9, 20).build()
    [(_, decisions)] = _decisions(md)
    assert [(d.frame, d.kind, d.completed) for d in decisions] == [(20, "carry", True), (40, "pass", True)]
