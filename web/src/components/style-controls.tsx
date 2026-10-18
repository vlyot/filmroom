import { BookOpenIcon, SlidersHorizontalIcon } from "lucide-react"

import type { Sliders } from "@/contracts"
import { language, SUPPORTED_LANGUAGES } from "@/lib/narrative"
import type { Audience } from "@/lib/source/types"
import { useActiveStyle, usePreferences } from "@/state/preferences"
import { StyleCard } from "@/components/style-card"
import { Button } from "@/components/ui/button"
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Slider } from "@/components/ui/slider"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

const CUSTOM = "custom"
const AUDIENCES: { value: Audience; label: string }[] = [
  { value: "coach", label: "Coach" },
  { value: "player", label: "Player" },
  { value: "fan", label: "Fan" },
]

/** The lens and the voice: tactical style (a preset or custom sliders), audience and language. */
export function StyleControls() {
  const {
    style: choice,
    styles,
    audience,
    language: code,
    set,
  } = usePreferences()
  const { style, presetId } = useActiveStyle()
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={choice.kind === "preset" ? choice.id : CUSTOM}
        onValueChange={(value) =>
          set({
            style:
              value === CUSTOM
                ? { kind: "custom", base: presetId, sliders: style.sliders }
                : { kind: "preset", id: value },
          })
        }
      >
        <SelectTrigger size="sm" className="w-52" aria-label="Tactical style">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectLabel>Presets</SelectLabel>
            {styles.map((s) => (
              <SelectItem key={s.id} value={s.id}>
                {s.name}
              </SelectItem>
            ))}
          </SelectGroup>
          <SelectSeparator />
          <SelectItem value={CUSTOM}>Custom sliders</SelectItem>
        </SelectContent>
      </Select>
      <SlidersSheet />
      <HoverCard openDelay={150}>
        <HoverCardTrigger asChild>
          <Button size="sm" variant="ghost">
            <BookOpenIcon />
            Style card
          </Button>
        </HoverCardTrigger>
        <HoverCardContent className="w-96">
          <StyleCard />
        </HoverCardContent>
      </HoverCard>
      <ToggleGroup
        type="single"
        size="sm"
        variant="outline"
        spacing={0}
        value={audience}
        onValueChange={(value) => value && set({ audience: value as Audience })}
        aria-label="Audience"
      >
        {AUDIENCES.map((a) => (
          <ToggleGroupItem
            key={a.value}
            value={a.value}
            className="px-2.5 text-xs"
          >
            {a.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <Select value={code} onValueChange={(value) => set({ language: value })}>
        <SelectTrigger
          size="sm"
          className="w-28"
          aria-label="Narrative language"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {SUPPORTED_LANGUAGES.map((l) => (
            <SelectItem key={l} value={l}>
              {language(l).name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function SlidersSheet() {
  const { lens, styles, set } = usePreferences()
  const { style, presetId, isCustom } = useActiveStyle()
  const move = (update: Partial<Sliders>) =>
    set({
      style: {
        kind: "custom",
        base: presetId,
        sliders: { ...style.sliders, ...update },
      },
    })
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button size="sm" variant={isCustom ? "secondary" : "outline"}>
          <SlidersHorizontalIcon />
          Sliders
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Custom style</SheetTitle>
          <SheetDescription>
            Every verdict is re-judged in your browser as you move a slider.
            Each slider moves only its own factors, so a changed verdict names
            the slider behind it.
          </SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-6 px-4">
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">Principles from</span>
            <Select
              value={presetId}
              onValueChange={(base) =>
                set({ style: { kind: "custom", base, sliders: style.sliders } })
              }
            >
              <SelectTrigger
                size="sm"
                className="w-full"
                aria-label="Base preset"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {styles.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {lens.sliders.map((spec) => (
            <div key={spec.slider} className="flex flex-col gap-2">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium">{spec.label}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {style.sliders[spec.slider].toFixed(2)}
                </span>
              </div>
              <Slider
                value={[style.sliders[spec.slider]]}
                min={0}
                max={1}
                step={0.05}
                onValueChange={([value]) => move({ [spec.slider]: value })}
                aria-label={spec.label}
              />
              <p className="text-xs text-muted-foreground">{spec.statement}</p>
            </div>
          ))}
          {isCustom && (
            <Button
              variant="outline"
              onClick={() => set({ style: { kind: "preset", id: presetId } })}
            >
              Back to {styles.find((s) => s.id === presetId)!.name}
            </Button>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
