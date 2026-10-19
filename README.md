# FilmRoom

[![CI](https://github.com/vlyot/filmroom/actions/workflows/ci.yml/badge.svg)](https://github.com/vlyot/filmroom/actions/workflows/ci.yml)

**Live:** https://vlyot.github.io/filmroom/ (GitHub Pages, backed by an API on Railway; it falls back to a static bundle if the API is down)

AI film-room analyst for the Microsoft × Premier League "Inside the Game" hackathon. It finds the possessions where a clearly better option was available, judges the alternatives against a chosen tactical style, and explains them for coaches, players and fans.

The engine computes; the LLM explains. Every number shown comes from the deterministic engine.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.13) and Node 20+.

```bash
uv sync                      # Python deps
cp .env.example .env         # then fill in the paths and key
```

### Data

FilmRoom runs on the SoccER dataset (synthetic matches from the open-source Gameplay Football engine). The dataset is **not** in this repo. Download it from the authors and point `DATA_DIR` at the folder holding the `Match_*` directories.

> L. Morra, F. Manigrasso, G. Canto, C. Gianfrate, E. Guarino, F. Lamberti. "Slicing and Dicing Soccer: Automatic Detection of Complex Events from Spatio-Temporal Data." ICIAR 2020. Code: https://gitlab.com/grains2/slicing-and-dicing-soccer

Player and team names in the game parody real people, so FilmRoom replaces every name with a fictional one at load time.

Expected threat (xT) uses Karun Singh's published 12 × 8 grid: K. Singh, "Introducing Expected Threat (xT)", 2019, https://karun.in/blog/expected-threat.html.

## Engine

`filmroom.engine` splits each match into possessions as events arrive, lists every decision (passes, shots, and the final dribble when a player loses the ball without releasing it), values each alternative with a pass model, a dribble model, an xG model and xT, and picks the turning point. Each possession is analysed only on data up to the frame it closed, and every match is analysed with models fitted on the other matches (leave one match out).

## Tactical lens

`filmroom.style` judges every option under a coach's style. A style is four sliders (risk tolerance, verticality, press trigger, defensive line height); the factor weights are a linear function of them (`src/filmroom/styles.json`), and each factor is moved by at most one slider, so whenever two styles disagree the verdict change traces to one factor and the slider behind it. Six presets pair a with-the-ball rule set (Possession, Direct, Counter) with a without-the-ball one (High Press, Mid-Block, Low Block); every rule set states its principles with a source. The without-the-ball sliders weigh what losing the ball would cost: counter-press cover around where it would be lost, and how much of the space behind that spot the team still controls.

## Agent layer

`filmroom.agents` explains the engine's verdicts with Microsoft Agent Framework and Mistral (`mistral-small-2603`), calling the engine through MCP.

- **Narrator:** one call per flagged moment, audience (coach, player, fan), language (English, Spanish) and style. It writes text with `{slot}` placeholders and claims; code fills the slots from the engine, so the model never writes a number or a name.
- **Verifier:** plain code. It rejects digits, spelled-out numbers and names outside slots, unknown slots, and claims that contradict the verdict under the active style; a rejected draft is retried once, then the template is shown. A template is always shown first, and the verified narrative replaces it.
- **MCP server** at `/mcp`: six read-only engine tools (flagged moments, a possession, its turning point, options under a style, comparing styles, similar situations). Any MCP client can use them.
- **Analyst** (`POST /analyst`): a tool-calling agent over those tools. It writes no numbers; it cites the possessions it talks about, and the app shows their numbers from the engine.
- **Session pack** (`/matches/{id}/session-pack`): an Agent Framework workflow that ranks the team's flagged moments, counts how other presets would judge them, groups them into themes and narrates each.

Without `MISTRAL_API_KEY` everything still works on templates, and the analyst says it is offline. Every model call is logged with its tokens and counted against a daily cap (`LLM_DAILY_TOKEN_LIMIT`).

What the verifier can't promise: it checks numbers, names, slots and claims, not every shade of meaning. A sentence can still use a slot loosely ("a pass" where the best option was a dribble), and a real name that ends like an ordinary word ("-ando", "-ing") could open a sentence.

## Web app

`web/` (React 19, Vite, shadcn/ui) is the product: a match replay that flags possessions as they end, a breakdown of each flagged moment (pitch replay with option lanes, danger curve, options ranked under the style, factor by factor), style controls (six presets or four custom sliders), coach / player / fan in English or Spanish, the session pack, ask-the-analyst and the overlay feed.

- **Two data sources, one app.** With `VITE_API_URL` set and the API answering, the app is live: REST for data and a WebSocket replay (`/matches/{id}/replay`) that plays the stored analyses on a match clock (1×–10×), streams positions at 10 Hz, sends each flag as the clock passes the possession's end and pushes the verified narrative once it is written. Otherwise, or as soon as the API stops answering, it reads the static bundle and plays the same replay in the browser. The badge in the header says which, and switches by hand for a fallback drill.
- **Verdicts are computed in the browser.** `web/src/lib/lens.ts` and `web/src/lib/narrative.ts` port the style scoring and the slot filling; `contracts/parity.json` (written by `tests/web_parity.py` from the synthetic match) pins them to the Python, and both test suites check it. Slider drags never wait on the network, and offline mode judges custom styles too.
- **Overlay feed** (`/matches/{id}/overlay?style=`): one event per flagged moment with a fan caption in every language, filled from the same engine slots. It serves cached verified captions or templates and never starts LLM work.

## Deployment

- **GitHub Pages** serves the web app (the submitted URL), built by `.github/workflows/pages.yml` after CI passes on `main`. CI has no SoccER data, so the static bundle is exported locally and kept on the `bundle` GitHub release (`scripts/publish_bundle.py`); the workflow refuses a bundle exported under another contract version, so offline mode can't drift from the API.
- **Railway** runs the API from the `Dockerfile` (one replica, always on), deployed by CI's `deploy-api` job with `railway up` once every check has passed. A deployment that fails its `/health` check leaves the previous one serving.
- **Postgres with pgvector** on Railway, over private networking. Railway holds no SoccER data: `scripts/seed_db.py` copies engine output (matches, possessions, positions and situation vectors) from a machine that has the dataset, in one transaction. The API (`STORE=database`) reads only that, so it needs neither the dataset nor the engine's models and stays near 125 MB. "Similar situations" is a pgvector cosine search. The narrative cache and the LLM token ledger live there too and survive reseeds and redeploys, so the daily token cap holds across restarts.
- **Monitoring:** every LLM call, narrative and analyst reply is a JSON log line (Railway keeps them), and `/metrics` counts the same events: requests and server errors, LLM latency, tokens today against the cap and this month against Mistral's $10 allowance, narrative and analyst fallback rates, verifier rejections and live replays. The app's **Service status** page (from the mode badge) shows them; CPU and memory are on Railway's dashboard.

## Common commands

```bash
uv run pytest                                  # tests (real-data tests skip without DATA_DIR)
uv run python -m filmroom.contracts.export     # regenerate contracts/schema.json + openapi.json
uv run python scripts/build_fixtures.py        # local fixtures from the real data (gitignored)
uv run python scripts/export_bundle.py --public  # static bundle without position data
uv run python scripts/export_bundle.py --store engine --matches 2019_09_09_001,2019_09_14_001  # bundle from engine output
uv run python -m tests.web_parity              # regenerate contracts/parity.json after a lens or slot change
uv run python scripts/analyse_matches.py       # analyse every match into the engine cache (gitignored)
uv run filmroom-eval                           # what was on instead: engine alternatives vs the labels
uv run filmroom-eval --thresholds              # refit the flag threshold over all matches (no labels); writes engine/params.json
uv run filmroom-eval --calibration             # pass-model and xG calibration out of fold; plot in .cache/eval
uv run filmroom-eval --lens                    # preset disagreement, flip attribution, slider directions, flag rates
uv run uvicorn filmroom.api.app:app --reload   # API on :8000 (fixtures; STORE=engine for live analysis); MCP at /mcp
uv run python scripts/prewarm_narratives.py --match 2019_09_09_001 --top 5   # narrative cache: dry run, add --yes to spend
RUN_LLM_TESTS=1 uv run pytest tests/test_llm_live.py   # a few live Mistral calls (skipped otherwise)

# Database store tests: a throwaway pgvector Postgres (they reset its public schema)
docker run -d --name filmroom-pg -e POSTGRES_PASSWORD=postgres -p 55432:5432 pgvector/pgvector:pg17
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres uv run pytest

# Seed Railway's Postgres (dry run; add --yes to write) and publish the Pages bundle (dry run; add --yes)
railway run --service Postgres -- uv run python scripts/seed_db.py --url-env DATABASE_PUBLIC_URL --matches 2019_09_09_001,2019_09_10_001,2019_09_14_001
uv run python scripts/publish_bundle.py --matches 2019_09_09_001,2019_09_10_001,2019_09_14_001
```

Web app (`web/`, React + Vite + shadcn/ui):

```bash
cd web
npm install
npm run gen:contracts   # regenerate src/contracts.ts from contracts/schema.json
npm test                # unit and parity tests (Vitest)
npm run dev             # the static bundle in public/bundle; copy .env.example to .env.local to use the API
VITE_BASE=/filmroom/ npm run build   # for GitHub Pages (hash routes, so deep links work there)
```

Anything derived from the SoccER data (`fixtures/possessions`, `fixtures/matches`, `web/public/bundle`, `.cache`) is generated locally and gitignored; the dataset has no licence for redistribution.
