"""Seed the deployed API's Postgres with engine output, from a machine that has the dataset.

Replaces the matches, possessions, positions and situation vectors in one transaction (the narrative cache and
the token ledger stay), then adds the local narrative cache's entries the database lacks. It first prints what
it would replace and where; it writes only with --yes.

Usage, against Railway (the CLI injects the database's public URL without printing it):
  railway run --service Postgres -- uv run python scripts/seed_db.py --url-env DATABASE_PUBLIC_URL \\
      --matches 2019_09_09_001,2019_09_10_001,2019_09_14_001 [--public] [--yes]
Options:
  --from            engine (the default; needs DATA_DIR) or fixtures
  --matches         match IDs, comma-separated (default: every match in the source)
  --public          leave out positions and option coordinates
  --no-narratives   don't upload the local narrative cache (CACHE_DIR/agents)
  --url-env         the environment variable holding the database URL (default DATABASE_URL)
"""

import argparse
import os

import psycopg
from psycopg.conninfo import conninfo_to_dict

from filmroom.api.store import open_store
from filmroom.config import Settings
from filmroom.db.schema import ensure_schema, read_meta
from filmroom.db.seed import seed, upload_cache


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", choices=["engine", "fixtures"], default="engine")
    parser.add_argument("--matches", type=lambda s: s.split(","), default=None)
    parser.add_argument("--public", action="store_true")
    parser.add_argument("--no-narratives", action="store_true")
    parser.add_argument("--url-env", default="DATABASE_URL")
    parser.add_argument("--yes", action="store_true", help="write (otherwise only report)")
    args = parser.parse_args()

    url = os.environ.get(args.url_env)
    if not url:
        raise SystemExit(f"{args.url_env} is not set")
    target = conninfo_to_dict(url)
    where = f"{target.get('host')}:{target.get('port', 5432)}/{target.get('dbname')}"

    settings = Settings(store=args.source, database_url=None)
    source = open_store(settings)
    available = [m.id for m in source.matches()]
    if args.matches and (unknown := set(args.matches) - set(available)):
        raise SystemExit(f"not in the {args.source} store: {', '.join(sorted(unknown))}")
    match_ids = [m for m in available if not args.matches or m in args.matches]

    with psycopg.connect(url) as conn:
        ensure_schema(conn)
        current = read_meta(conn)
        print(
            f"{where}: seeded {current.get('seeded_at', 'never')} with {current.get('matches') or 'nothing'} "
            f"(contract {current.get('contract_version', '-')}, public {current.get('public', '-')})"
        )
        print(f"would replace it with {len(match_ids)} matches from {args.source}: {', '.join(match_ids)}")
        print(f"public={args.public}, narratives={'no' if args.no_narratives else 'upload missing'}")
        if not args.yes:
            print("Dry run. Add --yes to write.")
            return
        counts = seed(conn, source, match_ids, args.public)
        print(
            f"seeded {counts.matches} matches, {counts.possessions} possessions, {counts.positions} position "
            f"tracks, {counts.situations} situation vectors"
        )
        if not args.no_narratives:
            added = upload_cache(conn, settings.cache_dir / "agents")
            print(f"uploaded {added} cached narratives and themes")


if __name__ == "__main__":
    main()
