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

## Common commands

```bash
uv run pytest                                  # tests (real-data tests skip without DATA_DIR)
uv run python -m filmroom.contracts.export     # regenerate contracts/schema.json + openapi.json
uv run python scripts/build_fixtures.py        # local fixtures from the real data (gitignored)
uv run python scripts/export_bundle.py --public  # static bundle without position data
uv run filmroom-eval --set tuning              # score turning points against the labels
uv run uvicorn filmroom.api.app:app --reload   # fixture-backed API on :8000
```

Web app (`web/`, React + Vite + shadcn/ui):

```bash
cd web
npm install
npm run gen:contracts   # regenerate src/contracts.ts from contracts/schema.json
npm run dev             # reads the static bundle from public/bundle
```

Anything derived from the SoccER data (`fixtures/possessions`, `fixtures/matches`, `web/public/bundle`, `.cache`) is generated locally and gitignored; the dataset has no licence for redistribution.
