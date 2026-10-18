"""Contract views shared by the engine and the fixtures: the match with its fictional roster, and a
possession's positions downsampled for the browser."""

import numpy as np

from filmroom.contracts.models import Match, PlayerRef, PositionsChunk, Possession, Team
from filmroom.data.catalog import MatchData, match_slug
from filmroom.data.positions import downsample


def mmss(ms: int) -> str:
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}"


def match_view(md: MatchData) -> Match:
    home, away = md.teams
    return Match(
        id=match_slug(md.info.id),
        title=f"{home.name} v {away.name}",
        mode=md.info.mode,
        duration_ms=int(md.clock.ms[-1]),
        has_events=md.has_events,
        teams=tuple(
            Team(side=t.side, key=t.key, name=t.name, attacks_towards_x=t.attacks_towards_x) for t in md.teams
        ),
        players=[
            PlayerRef(pid=p.pid, key=p.key, name=p.name, shirt=p.shirt, team=p.team, role=p.role)
            for p in md.players
        ],
    )


TAIL_MS = 1000


def possession_positions(md: MatchData, possession: Possession, hz: int = 10) -> PositionsChunk:
    """A possession's positions for the browser: from its start until a second after its last decision or its
    last owner row, whichever is later. The final pass is often kicked after the last owner row, and the
    viewer should see the decision and where the ball went."""
    last = max([possession.end_frame, *(d.frame for d in possession.decisions)])
    end = md.clock.frame_at(md.clock.ms_at(last) + TAIL_MS)
    return positions_chunk(md, possession.id, possession.start_frame, end, hz)


def positions_chunk(
    md: MatchData, possession_id: str, start_frame: int, end_frame: int, hz: int = 10
) -> PositionsChunk:
    samples = downsample(md.track.window(start_frame, end_frame), md.clock, hz=hz)
    return PositionsChunk(
        possession_id=possession_id,
        t0_ms=md.clock.ms_at(int(samples.frames[0])),
        hz=hz,
        pids=[int(p) for p in samples.pids],
        xy=[[None if np.isnan(v) else round(float(v), 2) for v in row.ravel()] for row in samples.xy],
    )
