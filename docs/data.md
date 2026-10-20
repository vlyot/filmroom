# Data

## SoccER

FilmRoom runs on SoccER, a dataset of synthetic football matches generated with the open-source Gameplay Football engine: per-frame positions of all 22 players and the ball, plus an event log.

> L. Morra, F. Manigrasso, G. Canto, C. Gianfrate, E. Guarino, F. Lamberti. "Slicing and Dicing Soccer: Automatic Detection of Complex Events from Spatio-Temporal Data." ICIAR 2020. Code: https://gitlab.com/grains2/slicing-and-dicing-soccer

The dataset is **not** in this repository. Download it from the authors and point `DATA_DIR` at the folder holding the `Match_*` directories (see [development](development.md)).

Expected threat (xT) uses Karun Singh's published 12 × 8 grid: K. Singh, "Introducing Expected Threat (xT)", 2019, https://karun.in/blog/expected-threat.html.

## Our synthetic data pipeline

SoccER gives raw positions and events. FilmRoom extends it into the layers a film session needs, all derived on load and cached locally:

- **Possessions**, split incrementally as events arrive, so a live replay can close each one when it ends.
- **Decision snapshots**: every pass, shot, and the final carry when a player loses the ball without releasing it, with everyone's position at that frame.
- **Alternatives** at each decision: every teammate as a pass target, a carry and a shot, valued with a pass model, a dribble model, an xG model and xT.
- **Pitch control and pressure** around the ball, and how much of the space behind a lost ball the team still controls.
- **Style factors** for each option (progression, switch of play, counter-press cover, rest defence and others), which the tactical lens weighs.

The pass and xG models are fitted on the dataset's own outcomes, leaving each match out of the models that analyse it ([evaluation](evaluation.md)).

## Fictional identities

The game's player and team names parody real people and clubs. FilmRoom replaces every name with a fictional one at load time (`src/filmroom/data/names.json`), and the app, the API, the narratives and the demo use only those. No game footage appears anywhere public.

## What is published

- **The live app** serves engine output for three matches (positions included) from the API and from the static bundle on the `bundle` GitHub release, with this citation.
- **This repository** holds no SoccER files and nothing derived from them: `fixtures/possessions`, `fixtures/matches`, `web/public/bundle` and `.cache` are generated locally and gitignored. The dataset states no licence for redistribution.
- The [MIT licence](../LICENSE) covers the code only.
