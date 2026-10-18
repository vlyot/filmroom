import { useEffect, useState, type ReactNode } from "react"
import { ActivityIcon, AlertCircleIcon } from "lucide-react"
import { toast } from "sonner"

import type { Latency, MetricsReport, OutcomeMetrics } from "@/contracts"
import type { Mode } from "@/lib/source/types"
import { useSource, useSourceState } from "@/state/source"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"

const POLL_MS = 10_000

type Polled = { mode: Mode; report: MetricsReport | null; error: Error | null }

/** The live API's metrics, refreshed every few seconds; null until the first answer in this mode. */
function useMetrics(): Polled | null {
  const source = useSource()
  const { mode } = useSourceState()
  const [polled, setPolled] = useState<Polled | null>(null)
  useEffect(() => {
    let current = true
    const poll = () =>
      source.metrics().then(
        (report) => current && setPolled({ mode, report, error: null }),
        (error: unknown) =>
          current &&
          setPolled({
            mode,
            report: null,
            error: error instanceof Error ? error : new Error(String(error)),
          })
      )
    void poll()
    const timer = setInterval(poll, POLL_MS)
    return () => {
      current = false
      clearInterval(timer)
    }
  }, [source, mode])
  return polled?.mode === mode ? polled : null
}

export function StatusPage() {
  const polled = useMetrics()
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Service status
        </h1>
        <p className="text-muted-foreground">
          The live API&apos;s own counters since it started, refreshed every{" "}
          {POLL_MS / 1000} seconds. CPU and memory are on Railway&apos;s
          dashboard.
        </p>
      </div>
      {polled === null && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      )}
      {polled?.error && (
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>No metrics</AlertTitle>
          <AlertDescription>{polled.error.message}</AlertDescription>
        </Alert>
      )}
      {polled && !polled.error && polled.report === null && <OfflineStatus />}
      {polled?.report && <Report report={polled.report} />}
    </div>
  )
}

function OfflineStatus() {
  const source = useSource()
  const { hasApi } = useSourceState()
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ActivityIcon />
        </EmptyMedia>
        <EmptyTitle>Offline</EmptyTitle>
        <EmptyDescription>
          The app is running from the static bundle, so there is no service to
          report on. The replay and every verdict still work in your browser.
        </EmptyDescription>
      </EmptyHeader>
      {hasApi && (
        <EmptyContent>
          <Button
            variant="outline"
            onClick={async () => {
              if (!(await source.goLive()))
                toast.error("The live API isn't answering")
            }}
          >
            Try the live API
          </Button>
        </EmptyContent>
      )}
    </Empty>
  )
}

const integer = new Intl.NumberFormat("en")
const usd = new Intl.NumberFormat("en", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 3,
})

function percent(rate: number | null | undefined): string {
  return rate == null ? "–" : `${Math.round(rate * 1000) / 10}%`
}

function ms(latency: Latency): string {
  const one = (v: number | null) =>
    v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`
  return `${one(latency.p50_ms)} · ${one(latency.p95_ms)}`
}

function uptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor(seconds / 60) % 60
  return h ? `${h} h ${m} min` : `${m} min`
}

function Stats({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="text-right font-medium tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function Share({
  label,
  used,
  of,
}: {
  label: string
  used: number
  of: number
}) {
  const value = Math.min(100, (used / of) * 100)
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span className="tabular-nums">{Math.round(value * 10) / 10}%</span>
      </div>
      <Progress value={value} aria-label={label} />
    </div>
  )
}

function Outcomes({
  title,
  description,
  outcomes,
}: {
  title: string
  description: string
  outcomes: OutcomeMetrics
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <Stats
          rows={[
            ["Verified", integer.format(outcomes.verified)],
            ["Fell back", integer.format(outcomes.fallback)],
            ["Fallback rate", percent(outcomes.fallback_rate)],
            ["Verifier rejected a draft", percent(outcomes.rejection_rate)],
          ]}
        />
      </CardContent>
    </Card>
  )
}

function Report({ report }: { report: MetricsReport }) {
  const { llm, requests } = report
  return (
    <>
      <div className="flex flex-wrap gap-2">
        <Badge variant="secondary">Up {uptime(report.uptime_s)}</Badge>
        <Badge variant="outline">Store: {report.source}</Badge>
        <Badge variant="outline">Contract {report.contract_version}</Badge>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Mistral allowance</CardTitle>
            <CardDescription>
              Estimated at Mistral Small 4 prices; spend past the allowance is
              capped at $0.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {llm.month_cost_usd != null && (
              <Share
                label={`This month: ${usd.format(llm.month_cost_usd)} of ${usd.format(llm.allowance_usd)}`}
                used={llm.month_cost_usd}
                of={llm.allowance_usd}
              />
            )}
            {llm.daily_token_limit != null && (
              <Share
                label={`Today: ${integer.format(llm.tokens_today)} of ${integer.format(llm.daily_token_limit)} tokens`}
                used={llm.tokens_today}
                of={llm.daily_token_limit}
              />
            )}
            {llm.month_tokens != null && llm.month_calls != null && (
              <Stats
                rows={[
                  ["Calls this month", integer.format(llm.month_calls)],
                  ["Tokens this month", integer.format(llm.month_tokens)],
                ]}
              />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>LLM calls</CardTitle>
            <CardDescription>
              Every model call since start-up, tool-calling steps included.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Stats
              rows={[
                ["Calls", integer.format(llm.calls)],
                ["Errors", integer.format(llm.errors)],
                ["Latency p50 · p95", ms(llm.latency)],
              ]}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Requests</CardTitle>
            <CardDescription>
              HTTP requests to the API; live replays are WebSockets.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Stats
              rows={[
                ["Requests", integer.format(requests.count)],
                ["Server errors", integer.format(requests.errors)],
                ["Latency p50 · p95", ms(requests.latency)],
                ["Live replays now", integer.format(report.replays_active)],
                [
                  "Replays since start-up",
                  integer.format(report.replays_total),
                ],
              ]}
            />
          </CardContent>
        </Card>
        <Outcomes
          title="Narratives"
          description="Written by the narrator and checked by the verifier; a fallback serves the template."
          outcomes={report.narratives}
        />
        <Outcomes
          title="Analyst"
          description="Replies from ask-the-analyst; a fallback lists the moments found."
          outcomes={report.analyst}
        />
      </div>
    </>
  )
}
