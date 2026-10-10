import numpy as np

from filmroom.data import files
from filmroom.data.frame_times import FrameClock
from filmroom.data.positions import downsample, parse_positions
from filmroom.data.textlog import (
    BallOut,
    Cross,
    Deflection,
    Foul,
    Goal,
    Kick,
    PassComplete,
    PassStart,
    Shot,
    Tackle,
    event_from_dict,
    event_to_dict,
    parse_textlog,
    read_roster,
)
from tests.conftest import MINI_MATCH, N_FRAMES


def test_resolves_file_name_variants_case_insensitively(mini_root):
    match_dir = mini_root / MINI_MATCH
    assert files.resolve(match_dir, *files.TEXTLOG).name == "Textual annotation.txt"
    assert files.resolve(match_dir, *files.VIDEO).name == "Recording.MKV"
    assert files.resolve(match_dir, "nope.txt") is None


def test_positions_parse_into_ball_then_team0_then_team1(mini_root):
    track = parse_positions(mini_root / MINI_MATCH / "positions.log")
    assert track.xy.shape == (N_FRAMES, 23, 2)
    assert track.pids.tolist() == [128, *range(11), *range(146, 157)]
    assert track.xy[0, 1].tolist() == [np.float32(1.0), np.float32(0.0)]


def test_positions_mark_missing_entities_as_nan(mini_root):
    track = parse_positions(mini_root / MINI_MATCH / "positions.log")
    assert track.missing == 1
    assert np.isnan(track.xy[4, -1]).all()


def test_frame_at_returns_first_frame_at_or_after_ms(mini_root):
    clock = FrameClock.from_csv(mini_root / MINI_MATCH / "frame_times.csv")
    assert clock.frame_at(52) == 1
    assert clock.frame_at(53) == 2
    assert clock.ms_at(11) == 152
    assert clock.frame_at(10**9) == N_FRAMES


def test_downsample_picks_nearest_frame_per_step_of_game_time(mini_root):
    match_dir = mini_root / MINI_MATCH
    track = parse_positions(match_dir / "positions.log")
    clock = FrameClock.from_csv(match_dir / "frame_times.csv")
    assert downsample(track, clock, hz=10).frames.tolist() == [1, 11, 21]


def test_roster_maps_team1_ids_to_128_plus_id(mini_root):
    roster = read_roster(mini_root / MINI_MATCH / "Textual annotation.txt")
    assert len(roster) == 22
    gk1 = next(r for r in roster if r.team == 1 and r.role == "GK")
    assert (gk1.text_id, gk1.pid) == (18, 146)


def test_textlog_parses_every_event_type(mini_root):
    log = parse_textlog(mini_root / MINI_MATCH / "Textual annotation.txt")
    assert log.events == [
        Kick(3, 5),
        PassStart(3, 5, "short"),
        PassComplete(6, 3, 5, 7, through_ball=False),
        PassStart(7, 151, "long"),
        PassComplete(9, 7, 151, 156, through_ball=True),
        Cross(10, 8, 9, 5, success=False),
        Shot(12, 11, 9, "saved", goalkeeper=146),
        Shot(14, 13, 152, "off_target"),
        Shot(16, 15, 8, "goal"),
        Goal(17, 8),
        Tackle(19, 18, victim=7, tackler=151, outcome="lose"),
        BallOut(20, "throw_in"),
        Foul(21, 3, "penalty", "yellow card"),
        Deflection(22, 146),
    ]


def test_textlog_records_possession_per_frame(mini_root):
    log = parse_textlog(mini_root / MINI_MATCH / "Textual annotation.txt")
    assert log.possession_frames.tolist() == [2, 3, 7]
    assert log.possession_pids.tolist() == [5, 5, 151]


def test_textlog_counts_unparsed_lines_instead_of_dropping_them(mini_root):
    log = parse_textlog(mini_root / MINI_MATCH / "Textual annotation.txt")
    assert dict(log.unparsed) == {"mystery event": 1}


def test_events_round_trip_through_dicts(mini_root):
    log = parse_textlog(mini_root / MINI_MATCH / "Textual annotation.txt")
    assert [event_from_dict(event_to_dict(e)) for e in log.events] == log.events
