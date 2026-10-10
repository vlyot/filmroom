"""Build local fixtures (gitignored) from the real data and fixtures/fixture_spec.json.

Usage: uv run python scripts/build_fixtures.py
"""

from pydantic import TypeAdapter

from filmroom.config import Settings
from filmroom.contracts.models import StyleConfig
from filmroom.data.catalog import Catalog
from filmroom.eval.labels import load_labels
from filmroom.fixtures import FixtureSpec, build_match, build_possession, write_fixtures


def main() -> None:
    settings = Settings()
    catalog = Catalog(settings)
    root = settings.fixtures_dir
    spec = FixtureSpec.model_validate_json((root / "fixture_spec.json").read_bytes())
    styles = TypeAdapter(list[StyleConfig]).validate_json((root / "styles.json").read_bytes())
    labels = {r.id: r for r in load_labels(settings.labels_path, "tuning", lambda m: catalog.load(m).clock)}

    matches, fixtures = {}, []
    for ps in spec.possessions:
        label = labels[ps.label_id]
        md = catalog.load(label.match_id)
        matches.setdefault(label.match_id, build_match(md))
        fixtures.append(build_possession(label, md, ps, spec.routine, spec.narratives, styles))
    write_fixtures(root, list(matches.values()), fixtures)
    for f in fixtures:
        p = f.possession
        flips = [v.style_id for v in p.verdicts.values() if v.flip_reason]
        summary = f"{len(p.decisions)} decisions, turning point #{p.turning_point_idx}, flips: {flips}"
        print(f"{f.label_id} -> {p.id}: {summary}")


if __name__ == "__main__":
    main()
