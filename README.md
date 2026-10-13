# FilmRoom

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

## Common commands

```bash
uv run pytest                                  # tests (real-data tests skip without DATA_DIR)
uv run python -m filmroom.contracts.export     # regenerate contracts/schema.json + openapi.json
uv run python scripts/build_fixtures.py        # local fixtures from the real data (gitignored)
uv run python scripts/export_bundle.py --public  # static bundle without position data
uv run python scripts/analyse_matches.py       # analyse every match into the engine cache (gitignored)
uv run filmroom-eval                           # what was on instead: engine alternatives vs the labels
uv run filmroom-eval --thresholds              # refit the flag threshold over all matches (no labels); writes engine/params.json
uv run filmroom-eval --calibration             # pass-model and xG calibration out of fold; plot in .cache/eval
uv run filmroom-eval --lens                    # preset disagreement, flip attribution, slider directions, flag rates
uv run uvicorn filmroom.api.app:app --reload   # API on :8000 (fixtures; STORE=engine for live analysis)
```

Web app (`web/`, React + Vite + shadcn/ui):

```bash
cd web
npm install
npm run gen:contracts   # regenerate src/contracts.ts from contracts/schema.json
npm run dev             # reads the static bundle from public/bundle
```

Anything derived from the SoccER data (`fixtures/possessions`, `fixtures/matches`, `web/public/bundle`, `.cache`) is generated locally and gitignored; the dataset has no licence for redistribution.
