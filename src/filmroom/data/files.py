from pathlib import Path

POSITIONS = ("positions.log",)
FRAME_TIMES = ("frame_times.csv",)
TEXTLOG = ("Textual annotations.txt", "Textual annotation.txt")
VIDEO = ("recording.mkv",)


def resolve(match_dir: Path, *candidates: str) -> Path | None:
    """Find a file by any of its known names, ignoring case (the dataset mixes both)."""
    wanted = {c.lower() for c in candidates}
    return next((p for p in match_dir.iterdir() if p.name.lower() in wanted), None)
