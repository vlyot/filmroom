# Development

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.13) and Node 20+.

```bash
uv sync                      # Python deps
cp .env.example .env         # then fill in the paths and key
cd web && npm install
```

The SoccER dataset isn't in the repo; download it and set `DATA_DIR` (see [data](data.md)). Without it, everything runs on the committed synthetic fixtures and the tests that need real data skip. Without `MISTRAL_API_KEY`, narratives are templates and the analyst says it is offline.

## Layout

| Path | What |
| --- | --- |
| `src/filmroom/data` | Loader, possession splitter, fictional identities |
| `src/filmroom/engine` | Decisions, options, pass / dribble / xG models, xT, pitch control, turning point |
| `src/filmroom/style.py`, `styles.json` | The tactical lens: presets, sliders, factor weights, flip reasons |
| `src/filmroom/agents` | Narrator, verifier, MCP server, analyst, session pack, cache, token budget |
| `src/filmroom/api` | FastAPI app, WebSocket replay, the fixture / engine / database stores, bundle export |
| `src/filmroom/db` | Postgres schema, seed, narrative cache and token ledger |
| `src/filmroom/eval` | Labels, scoring, calibration, lens checks (`filmroom-eval`) |
| `contracts/` | JSON Schema, OpenAPI and the browser parity file, generated from the Pydantic models |
| `web/` | The React app (Vite, shadcn/ui) |
| `scripts/` | Fixtures, analysis cache, bundle export and publish, seed, prewarm, demo moments |

## Common commands

```bash
uv run pytest                                  # tests (real-data tests skip without DATA_DIR)
uv run python -m filmroom.contracts.export     # regenerate contracts/schema.json + openapi.json
uv run python scripts/build_fixtures.py        # local fixtures from the real data (gitignored)
uv run python -m tests.web_parity              # regenerate contracts/parity.json after a lens or slot change
uv run python scripts/analyse_matches.py       # analyse every match into the engine cache (gitignored)
uv run uvicorn filmroom.api.app:app --reload   # API on :8000 (fixtures; STORE=engine for live analysis); MCP at /mcp

uv run filmroom-eval                           # what was on instead: engine alternatives vs the labels
uv run filmroom-eval --lens                    # ... plus preset disagreement, flip attribution, slider directions, flag rates
uv run filmroom-eval --calibration             # pass-model and xG calibration out of fold; plot in .cache/eval
uv run filmroom-eval --thresholds              # refit the flag threshold over all matches (no labels); writes engine/params.json

STORE=engine uv run python scripts/demo_moments.py --matches 2019_09_14_001   # flagged moments, headline-pair flips first
uv run python scripts/prewarm_narratives.py --match 2019_09_09_001 --top 5    # narrative cache: dry run, add --yes to spend
RUN_LLM_TESTS=1 uv run pytest tests/test_llm_live.py                          # a few live Mistral calls (skipped otherwise)

# Database store tests: a throwaway pgvector Postgres (they reset its public schema)
docker run -d --name filmroom-pg -e POSTGRES_PASSWORD=postgres -p 55432:5432 pgvector/pgvector:pg17
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres uv run pytest
```

Each eval run writes JSON to `.cache/eval`, stamped with the commit it ran on and whether the tree had uncommitted changes.

Web app (`web/`):

```bash
npm run gen:contracts   # regenerate src/contracts.ts from contracts/schema.json
npm test                # unit and parity tests (Vitest)
npm run lint && npm run typecheck
npm run dev             # the static bundle in public/bundle; copy .env.example to .env.local to use the API
VITE_BASE=/filmroom/ npm run build   # for GitHub Pages (hash routes, so deep links work there)
```

## Deploy

- **API:** every push to `main` runs CI (ruff, pytest with a pgvector service, the web checks, a Docker build that must answer `/health`); then `deploy-api` runs `railway up` with the `RAILWAY_TOKEN` secret. Railway keeps the previous deployment if the new one fails its healthcheck.
- **Web:** `pages.yml` runs after CI passes on `main`. It downloads `bundle.tar.gz` from the `bundle` release, refuses one exported under another contract version, builds with `vars.API_URL` and deploys to Pages.
- **Data:** the database and the bundle are filled from a machine with the dataset. All three scripts are dry runs without `--yes`:

```bash
MATCHES=2019_09_09_001,2019_09_10_001,2019_09_14_001
# Reseed Railway's Postgres (replaces the derived tables in one transaction; keeps the cache and token ledger)
railway run --service pgvector -- uv run python scripts/seed_db.py --url-env DATABASE_URL --matches $MATCHES
# Fill the deployed narrative cache, then publish a bundle that carries those narratives
railway run --service pgvector -- env STORE=engine uv run python scripts/prewarm_narratives.py --match 2019_09_14_001 --top 10
railway run --service pgvector -- uv run python scripts/publish_bundle.py --matches $MATCHES
```

A schema or contract change needs a reseed and a new bundle; the API refuses to start on a database seeded under another version, so the old deployment keeps serving until then.

## Monitoring

`GET /metrics` (and the app's **Service status** page, from the mode badge) reports requests and server errors, LLM latency, tokens today against the daily cap and this month's estimated cost against Mistral's allowance, narrative and analyst fallback rates, verifier rejections and live replays. Every LLM call, narrative and analyst reply is also a JSON log line in Railway. CPU and memory are on Railway's dashboard.
