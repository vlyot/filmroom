import {
  AlertCircleIcon,
  CopyIcon,
  DownloadIcon,
  RadioTowerIcon,
} from "lucide-react"
import { toast } from "sonner"

import type { Match } from "@/contracts"
import { useResource } from "@/hooks/use-resource"
import { mmss } from "@/lib/format"
import { language } from "@/lib/narrative"
import { download } from "@/lib/pack"
import { useActiveStyle, usePreferences } from "@/state/preferences"
import { useSource, useSourceState } from "@/state/source"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

/** The broadcast overlay feed: one event per flagged moment, with a fan caption in every language carrying
 * the same engine numbers. */
export function OverlayPage({ match }: { match: Match }) {
  const source = useSource()
  const { mode } = useSourceState()
  const { presetId } = useActiveStyle()
  const { styles } = usePreferences()
  const events = useResource(`${mode}:overlay:${match.id}:${presetId}`, () =>
    source.overlay(match.id, presetId)
  )
  const feedUrl = source.overlayUrl(match.id, presetId)
  const styleName = styles.find((s) => s.id === presetId)!.name

  if (events.status === "loading")
    return <Skeleton className="h-96 w-full rounded-xl" />
  if (events.status === "error") {
    return (
      <Alert variant="destructive">
        <AlertCircleIcon />
        <AlertTitle>No overlay feed</AlertTitle>
        <AlertDescription>{events.error.message}</AlertDescription>
      </Alert>
    )
  }
  const json = JSON.stringify(events.data, null, 2)
  const languages = Object.keys(events.data[0]?.captions ?? {})
  return (
    <div className="flex flex-col gap-6">
      {feedUrl && (
        <Item variant="muted">
          <ItemMedia variant="icon">
            <RadioTowerIcon />
          </ItemMedia>
          <ItemContent>
            <ItemTitle>Live feed</ItemTitle>
            <ItemDescription className="font-mono text-xs break-all">
              GET {feedUrl}
            </ItemDescription>
          </ItemContent>
        </Item>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Captions</CardTitle>
          <CardDescription>
            {events.data.length} moments under {styleName}. Each caption fills
            the same engine slots in every language.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                {languages.map((l) => (
                  <TableHead key={l}>{language(l).name}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.data.map((event) => (
                <TableRow key={event.possession_id}>
                  <TableCell className="font-mono text-xs">
                    {mmss(event.t_ms)}
                  </TableCell>
                  {languages.map((l) => (
                    <TableCell key={l} className="whitespace-normal" lang={l}>
                      {event.captions[l]}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <div className="flex flex-col gap-1.5">
            <CardTitle>JSON</CardTitle>
            <CardDescription>
              OverlayEvent[], as in contracts/schema.json
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                navigator.clipboard.writeText(json).then(
                  () => toast.success("Overlay JSON copied"),
                  () => toast.error("Couldn't copy to the clipboard")
                )
              }
            >
              <CopyIcon />
              Copy
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                download(
                  `filmroom-overlay-${match.id}-${presetId}.json`,
                  json,
                  "application/json"
                )
              }
            >
              <DownloadIcon />
              Download
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <ScrollArea className="h-96 rounded-md border bg-muted/30">
            <pre className="p-4 font-mono text-xs">{json}</pre>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  )
}
