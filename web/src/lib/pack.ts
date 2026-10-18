import type { Match, PackMoment, SessionPack, StyleConfig } from "@/contracts"
import { mmss, OUTCOME_LABELS, ZONE_LABELS } from "@/lib/format"
import { language, renderNarrative } from "@/lib/narrative"

/** When the moment's decision was taken, as its narrative says it (the possession can end a little later). */
export function momentTime(moment: PackMoment): string {
  return String(
    moment.narrative.facts["tp.time"]?.value ?? mmss(moment.summary.end_ms)
  )
}

/** The session pack as a Markdown handout: themes, the ranked moments with their narratives, and how the
 * other presets would judge them. */
export function packMarkdown(
  pack: SessionPack,
  match: Match,
  styles: StyleConfig[]
): string {
  const style = styles.find((s) => s.id === pack.style_id)!
  const team = match.teams[pack.team].name
  const factors = language("en").factors
  const lines = [
    `# ${team}: ${pack.period === "half" ? "half-time" : "full-time"} session`,
    "",
    `${match.title} · judged under ${style.name} · for the ${pack.audience}`,
    "",
  ]
  if (pack.themes.length) {
    lines.push("## Themes", "")
    for (const theme of pack.themes) {
      const ranks = pack.moments
        .filter((m) => theme.possession_ids.includes(m.summary.id))
        .map((m) => `#${m.rank}`)
      lines.push(
        `### ${theme.title}`,
        "",
        theme.summary,
        "",
        `Moments: ${ranks.join(", ")}`,
        ""
      )
    }
  }
  lines.push("## Moments", "")
  for (const moment of pack.moments) {
    const { summary, narrative } = moment
    lines.push(
      `### #${moment.rank} · ${momentTime(moment)} · ${OUTCOME_LABELS[summary.outcome]} in the ${ZONE_LABELS[summary.ended_zone]}`,
      "",
      renderNarrative(narrative.template, narrative.facts, narrative.language),
      ""
    )
  }
  if (pack.style_shifts.length) {
    lines.push(
      "## Under other styles",
      "",
      "| Style | Moments judged differently | Mostly because of |",
      "|---|---|---|"
    )
    for (const shift of pack.style_shifts) {
      const why = shift.factor ? factors[shift.factor] : "—"
      lines.push(
        `| ${shift.name} | ${shift.changed} of ${pack.moments.length} | ${why} |`
      )
    }
    lines.push("")
  }
  lines.push(
    "Every number above comes from the FilmRoom engine; the text around it was checked by code.",
    ""
  )
  return lines.join("\n")
}

export function download(filename: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
