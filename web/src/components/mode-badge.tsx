import { ActivityIcon, ChevronDownIcon } from "lucide-react"
import { toast } from "sonner"

import { href } from "@/lib/router"
import { cn } from "@/lib/utils"
import { useSource, useSourceState } from "@/state/source"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

/** Where the data comes from, always visible: the live API or the offline bundle. It also switches by hand,
 * for the fallback drill. */
export function ModeBadge() {
  const source = useSource()
  const { mode, health, hasApi } = useSourceState()
  const live = mode === "live"
  const label = live
    ? health?.llm
      ? "Live"
      : "Live · analyst offline"
    : "Offline"
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          aria-label={`Data source: ${label}`}
        >
          <span
            className={cn(
              "size-2 rounded-full",
              live ? "bg-emerald-500" : "bg-muted-foreground"
            )}
          />
          {label}
          <ChevronDownIcon className="text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>Data source</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={mode}
          onValueChange={async (next) => {
            if (next === "offline") source.goOffline()
            else if (!(await source.goLive()))
              toast.error("The live API isn't answering")
          }}
        >
          <DropdownMenuRadioItem value="live" disabled={!hasApi}>
            Live API {hasApi ? "" : "(not configured)"}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="offline">
            Offline bundle
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <p className="px-2 py-1.5 text-xs text-muted-foreground">
          Offline, the replay and every verdict still run in your browser;
          narratives are the pre-generated ones, and the analyst is unavailable.
        </p>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <a href={href({ page: "status" })}>
            <ActivityIcon />
            Service status
          </a>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
