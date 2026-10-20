"""List candidate moments for the demo video: every flagged possession in the given matches, with the best
option under each preset. Moments where the headline pair (Possession + High Press vs Counter + Low Block)
picks different options come first, with the factor that flips them, because the video shows that switch.
Reads only; no LLM calls. Names are the fictional ones the store serves.

Usage: uv run python scripts/demo_moments.py --matches a,b [--top 15]
"""

import argparse

from filmroom.api.store import open_store
from filmroom.config import Settings
from filmroom.contracts.models import Match, Option, Possession
from filmroom.style import flip_reason, load_lens, presets_by_id

HEADLINE = ("possession-high-press", "counter-low-block")


def _clock(ms: int) -> str:
    return f"{ms // 60_000:02d}:{ms // 1000 % 60:02d}"


def _option(option: Option, names: dict[int, str]) -> str:
    target = names.get(option.target_pid) if option.target_pid is not None else None
    return f"{option.kind} to {target}" if target else option.kind


def candidates(possessions: list[Possession], match: Match) -> list[dict]:
    """One row per flagged possession: headline-pair flips first, then by severity."""
    styles = presets_by_id(load_lens())
    names = {p.pid: p.name for p in match.players}
    rows = []
    for p in possessions:
        if not p.flagged or p.turning_point_idx is None:
            continue
        decision = p.decisions[p.turning_point_idx]
        options = {o.id: o for o in decision.options}
        reason = flip_reason(decision, styles[HEADLINE[0]], styles[HEADLINE[1]])
        rows.append(
            {
                "id": p.id,
                "clock": f"{_clock(p.start_ms)}-{_clock(p.end_ms)}",
                "severity": p.severity,
                "outcome": p.outcome,
                "player": names.get(decision.pid, str(decision.pid)),
                "chose": _option(options[decision.chosen_option_id], names),
                "best": {
                    style_id: _option(options[v.best_option_id], names) for style_id, v in p.verdicts.items()
                },
                "flip": reason.factor if reason else None,
            }
        )
    return sorted(rows, key=lambda r: (r["flip"] is None, -r["severity"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matches", type=lambda s: s.split(","), required=True)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()
    store = open_store(Settings())
    for match_id in args.matches:
        match = store.match(match_id)
        rows = candidates(store.match_possessions(match_id), match)
        flips = sum(r["flip"] is not None for r in rows)
        print(f"\n{match.title} ({match_id}): {len(rows)} flagged, {flips} flip between the headline pair")
        for r in rows[: args.top]:
            flip = f"flips on {r['flip']}" if r["flip"] else "no headline flip"
            print(
                f"  {r['id']}  {r['clock']}  severity {r['severity']:.2f}  {r['outcome']:<11} {flip}\n"
                f"    {r['player']} chose {r['chose']}; "
                f"{HEADLINE[0]}: {r['best'].get(HEADLINE[0])}; {HEADLINE[1]}: {r['best'].get(HEADLINE[1])}"
            )


if __name__ == "__main__":
    main()
