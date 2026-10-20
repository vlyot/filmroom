# Decisions

The calls that shaped FilmRoom, grouped by the part of the build they belong to.

## Product and data

| Decision | Why |
| --- | --- |
| **The engine computes; the LLM explains.** Every number and name on screen comes from the deterministic engine; the model writes text around `{slot}` placeholders that code fills. | A coach can't act on a number a model may have invented. |
| **The possession is the unit**, with its decisions inside. | That's how film sessions are cut. |
| **Extend SoccER rather than build a generator**, and replace every name with a fictional one. | A generator from scratch costs more than the whole build window, and the game's names parody real players. |
| **Tactical style is a lens, not a property of the data.** | The game's bots don't play distinct tactics, so style has to be how a coach judges the options, not how the team played. |

## Engine and evaluation

| Decision | Why |
| --- | --- |
| **No blind holdout** (11 Oct). The 20-possession holdout was written but not labelled. | Time. The cost is stated in the [evaluation](evaluation.md): no independent check on turning points. |
| **The turning point is the final decision** (11 Oct). | The earlier-turning-point detector failed its gate (0 of 6). The bar it kept, "what was on instead", passed at 12 of 22. |
| **Lead with calibration**, report agreement with our labels as agreement, never accuracy. | The labels and the engine share an author; the pass outcomes don't. |
| **Shot success is the on-target rate; shot value is xG** (13 Oct). | Geometry doesn't predict hitting the target in SoccER (Brier 0.2503 vs 0.2500 base rate); xG beats its base rate (0.115 vs 0.135). |
| **Detector frozen at `bfa7a57`** (20 Oct) for the final evaluation. | So the reported numbers name the code that produced them. |

## Tactical lens

| Decision | Why |
| --- | --- |
| **Linear lens.** Option score is a weighted sum of factors, weights are a linear function of four sliders, and each factor is moved by at most one slider. | Every verdict change traces to one factor and the slider behind it, so the app can say why. |
| **Six presets** pair a with-the-ball rule set (Possession, Direct, Counter) with a without-the-ball one (High Press, Mid-Block, Low Block); every principle cites a source. | Coaches think in those two halves, and sliders let them set their own. |
| **Judge the lens by flip attribution and slider directions**, not by how often presets disagree. | A disagreement rate alone is easy to game. |
| **Pressing as transition factors on on-ball options** (13 Oct), not a new kind of decision. | Gives the without-the-ball sliders verdict-deciding factors without opponent-side possessions or new UI. |

## Agents

| Decision | Why |
| --- | --- |
| **Microsoft Agent Framework, with the engine as MCP tools.** The analyst calls the same six read-only tools any MCP client can. | One interface for agents, IDEs and tests. |
| **A code verifier, not a second model** (14 Oct). Drafts with numbers, names outside slots, unknown slots or claims that contradict the verdict are rejected, retried once, then replaced by the template. | Deterministic, testable (2,268 of 2,268 injected errors caught), and no extra calls. |
| **The analyst writes no numbers** (14 Oct); it cites possessions and the app shows their numbers from the engine. | Keeps "no LLM-written number reaches the screen" true for chat too. |
| **One narrator call per flagged moment, template first**, cached by everything that went into it; Mistral Small 4 with a $0 overage cap and a daily token cap. | The monthly allowance is the real limit, not the rate, and the endpoints are public. |

## Frontend and platform

| Decision | Why |
| --- | --- |
| **Verdicts computed in the browser.** The style scoring and slot filling are ported to TypeScript and pinned to the Python by a parity file both test suites check. | Slider drags never wait on the network, and offline mode judges custom styles too. |
| **A static bundle behind the same URL.** If the API stops answering, the app switches to the bundle and says so; it re-probes the API every minute and switches back (20 Oct). | The submitted URL has to work until judging ends, whatever happens to the API. |
| **Railway as the only API host; no Azure** (13 Oct). | The Azure free account ended five days before judging ends. Railway runs the same image for the whole window within its included usage. |
| **Postgres holds engine output; the API never runs the engine** (18 Oct). Seeded in one transaction from a machine with the dataset. | Railway can't hold the dataset, and the API stays near 130 MB. |
| **Exact pgvector search, no HNSW index** (18 Oct). | A few thousand vectors, and HNSW filters after the index scan, so a filtered query could return fewer than k. |
| **Deploy from GitHub Actions** once CI passes (18 Oct), not Railway's GitHub integration. | One pipeline, and a deployment that fails its healthcheck leaves the previous one serving. |
