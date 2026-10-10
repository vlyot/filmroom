"""Write holdout_labels.xlsx: 20 stratified candidate possessions for blind labelling from video.

Usage: uv run python scripts/make_holdout_sheet.py
"""

from collections import Counter

from filmroom.config import Settings
from filmroom.data.catalog import Catalog
from filmroom.eval.holdout import find_candidates, select_candidates, write_holdout_sheet
from filmroom.eval.labels import load_labels, load_offsets


def main() -> None:
    settings = Settings()
    catalog = Catalog(settings)
    offsets = load_offsets(settings.labels_path)
    tuning = load_labels(settings.labels_path, "tuning")
    candidates = [c for match_id in offsets for c in find_candidates(catalog.load(match_id))]
    chosen = select_candidates(candidates, exclude=tuning)
    modes = {m.id: m.mode.replace("_", " ") for m in catalog.matches()}
    write_holdout_sheet(chosen, modes, offsets, settings.holdout_path)
    print(f"{len(candidates)} candidates found; wrote {len(chosen)} to {settings.holdout_path}")
    print("by ending:", dict(Counter(c.ending for c in chosen)))
    print("by match:", dict(Counter(c.match_id for c in chosen)))


if __name__ == "__main__":
    main()
