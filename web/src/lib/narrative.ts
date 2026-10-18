// Narrative slots in the browser: the same rules as filmroom/agents/facts.py, reading the agent layer's own
// templates and language files at build time. Every narrative the app shows is filled here from its own
// `facts`; custom slider positions get a template narrative built here, since only presets are narrated.

import templates from "@agents/templates.json"

import type {
  Fact,
  Match,
  Narrative,
  Option,
  Possession,
  StyleConfig,
  Verdict,
} from "@/contracts"
import { mmss } from "@/lib/format"
import { toFixed, roundTo } from "@/lib/round"

type Audience = Narrative["audience"]

export type LanguagePack = {
  name: string
  decimal: string
  percent: string
  bands: Record<Option["p_success_band"], string>
  actions: { pass: string; space: string; carry: string; shot: string }
  factors: Record<string, string>
}

const PACKS = import.meta.glob<LanguagePack>(
  "../../../src/filmroom/agents/languages/*.json",
  {
    eager: true,
    import: "default",
  }
)

const LANGUAGES: Record<string, LanguagePack> = Object.fromEntries(
  Object.entries(PACKS).map(([path, pack]) => [
    path.split("/").pop()!.replace(".json", ""),
    pack,
  ])
)

/** Supported narrative languages, sorted like the API's supported_languages(). */
export const SUPPORTED_LANGUAGES = Object.keys(LANGUAGES).sort()

export function language(code: string): LanguagePack {
  const pack = LANGUAGES[code]
  if (!pack) throw new Error(`unsupported language: ${code}`)
  return pack
}

const SLOT = /\{([a-z0-9_.]+)\}/g

export function formatFact(fact: Fact, code: string): string {
  const lang = language(code)
  const value = Number(fact.value)
  switch (fact.kind) {
    case "prob":
      return lang.percent.replace("{value}", String(roundTo(value * 100)))
    case "xt":
      return `${value < 0 || Object.is(value, -0) ? "-" : "+"}${toFixed(Math.abs(value), 3)} xT`.replace(
        ".",
        lang.decimal
      )
    case "metres":
      return `${toFixed(value, 0)} m`
    case "count":
      return String(Math.trunc(value))
    case "band":
      return lang.bands[fact.value as Option["p_success_band"]]
    default:
      return String(fact.value)
  }
}

export function renderNarrative(
  template: string,
  facts: Record<string, Fact>,
  code: string
): string {
  return template.replace(SLOT, (_, id: string) => formatFact(facts[id], code))
}

function fact(value: number | string, kind: Fact["kind"]): Fact {
  return { value, kind, unit: null }
}

function playerName(match: Match, pid: number): string {
  return match.players.find((p) => p.pid === pid)!.name
}

export function actionPhrase(
  option: Option,
  match: Match,
  code: string
): string {
  const actions = language(code).actions
  if (option.kind === "pass") {
    if (option.target_pid === null) return actions.space
    return actions.pass.replace(
      "{player}",
      playerName(match, option.target_pid)
    )
  }
  return actions[option.kind]
}

/** The slots for a turning-point verdict under one style, as facts.narrative_facts builds them. */
export function narrativeFacts(
  possession: Possession,
  match: Match,
  judged: Verdict,
  style: StyleConfig,
  reference: StyleConfig,
  code: string
): Record<string, Fact> {
  const decision = possession.decisions[judged.decision_idx]
  const options = new Map(decision.options.map((o) => [o.id, o]))
  const chosen = options.get(judged.chosen_option_id)!
  const facts: Record<string, Fact> = {
    "tp.player": fact(playerName(match, decision.pid), "player"),
    "tp.time": fact(mmss(decision.t_ms), "text"),
    "chosen.action": fact(actionPhrase(chosen, match, code), "text"),
    "chosen.p_success": fact(chosen.p_success, "prob"),
    "chosen.p_success_band": fact(chosen.p_success_band, "band"),
    "style.name": fact(style.name, "text"),
  }
  if (judged.better_available) {
    const best = options.get(judged.best_option_id)!
    Object.assign(facts, {
      "best.action": fact(actionPhrase(best, match, code), "text"),
      "best.p_success": fact(best.p_success, "prob"),
      "best.p_success_band": fact(best.p_success_band, "band"),
      "best.danger_gain": fact(best.danger_gain, "xt"),
    })
  }
  if (judged.flip_reason) {
    Object.assign(facts, {
      "flip.factor": fact(
        language(code).factors[judged.flip_reason.factor],
        "text"
      ),
      "flip.vs_style": fact(reference.name, "text"),
    })
  }
  return facts
}

/** A template narrative for a verdict the browser computed (custom sliders), as templates.template_narrative
 * builds one for a preset. */
export function templateNarrative(
  possession: Possession,
  match: Match,
  judged: Verdict,
  style: StyleConfig,
  reference: StyleConfig,
  audience: Audience,
  code: string
): Narrative {
  const better = judged.better_available
  const key =
    `${audience}.${code}.${better ? "better" : "fits"}` as keyof typeof templates
  return {
    possession_id: possession.id,
    style_id: style.id,
    audience,
    language: code,
    template: templates[key],
    facts: narrativeFacts(possession, match, judged, style, reference, code),
    claims: [
      better
        ? { type: "better_option", ref: judged.best_option_id }
        : { type: "chosen_fits_style", ref: judged.chosen_option_id },
    ],
    status: "template",
    model: null,
  }
}
