import { useState } from "react"
import { MessageSquareTextIcon, SendIcon, WifiOffIcon } from "lucide-react"

import type {
  AnalystReply,
  AnalystRequest,
  ChatTurn,
  Match,
  PossessionSummary,
} from "@/contracts"
import { cn } from "@/lib/utils"
import { useActiveStyle, usePreferences } from "@/state/preferences"
import { useSource, useSourceState } from "@/state/source"
import { MomentCard } from "@/components/moment-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"

const HISTORY_TURNS = 6
const EXAMPLES = [
  "Show me possessions we lost in midfield after a switch of play.",
  "Which moments would Counter + Low Block judge differently?",
  "Where did a safer pass beat the one we chose?",
]

type Message = {
  role: "user" | "assistant"
  text: string
  reply?: AnalystReply
}

/** Ask-the-analyst: an agent over the engine's MCP tools. It writes no numbers; the moments it cites are
 * shown with the engine's own. */
export function AnalystSheet({
  match,
  possessions,
}: {
  match: Match
  possessions: PossessionSummary[]
}) {
  const source = useSource()
  const { mode, health } = useSourceState()
  const { presetId } = useActiveStyle()
  const { language } = usePreferences()
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState("")
  const [asking, setAsking] = useState(false)
  const offline = mode === "offline" || health?.llm === false
  const summaries = new Map(possessions.map((p) => [p.id, p]))

  const ask = async (question: string) => {
    if (!question.trim() || asking) return
    const history = messages
      .slice(-HISTORY_TURNS)
      .map((m): ChatTurn => ({ role: m.role, text: m.text.slice(0, 2000) }))
    setMessages((current) => [...current, { role: "user", text: question }])
    setDraft("")
    setAsking(true)
    try {
      const reply = await source.analyst({
        question: question.slice(0, 500),
        history: history as AnalystRequest["history"],
        match_id: match.id,
        style_id: presetId,
        language,
      })
      setMessages((current) => [
        ...current,
        { role: "assistant", text: reply.text, reply },
      ])
    } catch (error) {
      const text = `The analyst couldn't answer: ${error instanceof Error ? error.message : String(error)}`
      setMessages((current) => [...current, { role: "assistant", text }])
    } finally {
      setAsking(false)
    }
  }

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button size="sm" variant="outline">
          <MessageSquareTextIcon />
          Ask the analyst
        </Button>
      </SheetTrigger>
      <SheetContent className="flex w-full flex-col sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Ask the analyst</SheetTitle>
          <SheetDescription>
            An agent that queries the engine through MCP. It cites moments
            rather than writing numbers.
          </SheetDescription>
        </SheetHeader>
        {offline && (
          <Alert className="mx-4 w-auto">
            <WifiOffIcon />
            <AlertTitle>Live analyst offline</AlertTitle>
            <AlertDescription>
              {mode === "offline"
                ? "The app is reading the offline bundle. Replay, verdicts and narratives still work."
                : "No language model is available right now. Replay, verdicts and narratives still work."}
            </AlertDescription>
          </Alert>
        )}
        <ScrollArea className="min-h-0 flex-1 px-4">
          <div className="flex flex-col gap-4 pb-4">
            {messages.length === 0 && !offline && (
              <div className="flex flex-col gap-2">
                <span className="text-sm text-muted-foreground">Try:</span>
                {EXAMPLES.map((example) => (
                  <Button
                    key={example}
                    variant="secondary"
                    size="sm"
                    className="h-auto justify-start py-2 text-left whitespace-normal"
                    onClick={() => void ask(example)}
                  >
                    {example}
                  </Button>
                ))}
              </div>
            )}
            {messages.map((message, i) => (
              <div
                key={i}
                className={cn(
                  "flex flex-col gap-2 rounded-lg p-3 text-sm",
                  message.role === "user"
                    ? "ml-8 bg-primary text-primary-foreground"
                    : "mr-4 bg-muted"
                )}
              >
                <p className="whitespace-pre-wrap">{message.text}</p>
                {message.reply && message.reply.status !== "verified" && (
                  <Badge variant="outline" className="self-start">
                    {message.reply.status === "offline"
                      ? "analyst offline"
                      : "fallback answer"}
                  </Badge>
                )}
                {message.reply?.possession_ids.map((id) => {
                  const summary = summaries.get(id)
                  return summary ? (
                    <MomentCard key={id} summary={summary} match={match} />
                  ) : null
                })}
              </div>
            ))}
            {asking && (
              <div className="mr-4 flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                <Spinner /> Querying the engine…
              </div>
            )}
          </div>
        </ScrollArea>
        <form
          className="flex items-end gap-2 border-t p-4"
          onSubmit={(event) => {
            event.preventDefault()
            void ask(draft)
          }}
        >
          <Textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                void ask(draft)
              }
            }}
            maxLength={500}
            placeholder={
              offline ? "The analyst is offline" : "Ask about this match…"
            }
            disabled={offline || asking}
            className="min-h-10 resize-none"
            aria-label="Question"
          />
          <Button
            type="submit"
            size="icon"
            disabled={offline || asking || !draft.trim()}
            aria-label="Send"
          >
            <SendIcon />
          </Button>
        </form>
      </SheetContent>
    </Sheet>
  )
}
