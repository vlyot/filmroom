import { createContext, use, useMemo, useState, type ReactNode } from "react"

import type { Sliders, StyleConfig, StyleLens } from "@/contracts"
import { styleFromSliders } from "@/lib/lens"
import { SUPPORTED_LANGUAGES } from "@/lib/narrative"
import type { Audience } from "@/lib/source/types"

/** A preset, or custom slider positions on top of a preset (whose rule sets give the card's principles). */
export type StyleChoice =
  | { kind: "preset"; id: string }
  | { kind: "custom"; base: string; sliders: Sliders }

export type Preferences = {
  style: StyleChoice
  audience: Audience
  language: string
  playerPid: number | null
}

type PreferencesContext = Preferences & {
  set: (update: Partial<Preferences>) => void
  styles: StyleConfig[]
  lens: StyleLens
}

const STORAGE_KEY = "filmroom.preferences"
const Context = createContext<PreferencesContext | null>(null)

function stored(styles: StyleConfig[]): Preferences {
  const fallback: Preferences = {
    style: { kind: "preset", id: styles[0].id },
    audience: "coach",
    language: "en",
    playerPid: null,
  }
  try {
    const saved = {
      ...fallback,
      ...JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}"),
    } as Preferences
    const presetId =
      saved.style.kind === "preset" ? saved.style.id : saved.style.base
    const valid =
      styles.some((s) => s.id === presetId) &&
      SUPPORTED_LANGUAGES.includes(saved.language)
    return valid ? saved : fallback
  } catch {
    return fallback
  }
}

export function PreferencesProvider({
  styles,
  lens,
  children,
}: {
  styles: StyleConfig[]
  lens: StyleLens
  children: ReactNode
}) {
  const [preferences, setPreferences] = useState(() => stored(styles))
  const value = useMemo<PreferencesContext>(
    () => ({
      ...preferences,
      styles,
      lens,
      set: (update) =>
        setPreferences((current) => {
          const next = { ...current, ...update }
          try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
          } catch {
            // private windows and blocked storage: the choice just isn't remembered
          }
          return next
        }),
    }),
    [preferences, styles, lens]
  )
  return <Context value={value}>{children}</Context>
}

export function usePreferences(): PreferencesContext {
  return use(Context)!
}

export type ActiveStyle = {
  style: StyleConfig
  reference: StyleConfig
  /** The preset narratives, packs and the overlay are fetched for: the custom style's base preset. */
  presetId: string
  isCustom: boolean
}

export function useActiveStyle(): ActiveStyle {
  const { style: choice, styles, lens } = usePreferences()
  return useMemo(() => {
    const reference =
      styles.find((s) => s.id === lens.reference_style_id) ?? styles[0]
    if (choice.kind === "preset") {
      const style = styles.find((s) => s.id === choice.id)!
      return { style, reference, presetId: style.id, isCustom: false }
    }
    const base = styles.find((s) => s.id === choice.base)!
    const style = styleFromSliders(
      lens,
      base.with_ball,
      base.without_ball,
      choice.sliders
    )
    return { style, reference, presetId: base.id, isCustom: true }
  }, [choice, styles, lens])
}
