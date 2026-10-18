import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  XAxis,
  YAxis,
} from "recharts"

import type { Possession } from "@/contracts"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"

const config = {
  xt: { label: "Danger (xT)", color: "var(--team-0)" },
} satisfies ChartConfig

/** Expected threat across the possession, with each decision marked and the turning point highlighted.
 * Clicking a decision's line selects it. */
export function DangerCurve({
  possession,
  selectedIdx,
  onSelectDecision,
}: {
  possession: Possession
  selectedIdx: number
  onSelectDecision: (idx: number) => void
}) {
  const seconds = (ms: number) => (ms - possession.start_ms) / 1000
  const data = possession.danger_curve.map((p) => ({
    t: seconds(p.t_ms),
    xt: p.xt,
  }))
  // The final pass is often kicked after the last owner row, past the curve's end.
  const span = Math.max(
    data.at(-1)?.t ?? 0,
    ...possession.decisions.map((d) => seconds(d.t_ms))
  )
  const color = possession.team === 0 ? "var(--team-0)" : "var(--team-1)"
  return (
    <ChartContainer
      config={{ xt: { ...config.xt, color } }}
      className="aspect-auto h-44 w-full"
    >
      <LineChart
        accessibilityLayer
        data={data}
        margin={{ left: 0, right: 12, top: 16, bottom: 0 }}
      >
        <CartesianGrid vertical={false} />
        <XAxis
          dataKey="t"
          type="number"
          domain={[0, Math.ceil(span)]}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => `${v.toFixed(0)}s`}
        />
        <YAxis
          width={44}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) => v.toFixed(2)}
        />
        <ChartTooltip content={<ChartTooltipContent hideLabel />} />
        {possession.decisions.map((d) => (
          <ReferenceLine
            key={d.idx}
            x={seconds(d.t_ms)}
            stroke={
              d.is_turning_point ? "var(--flag)" : "var(--muted-foreground)"
            }
            strokeWidth={d.idx === selectedIdx ? 2.5 : 1}
            strokeDasharray={d.is_turning_point ? undefined : "3 3"}
            label={
              d.is_turning_point
                ? { value: "turning point", position: "top", fontSize: 10 }
                : undefined
            }
            className="cursor-pointer"
            onClick={() => onSelectDecision(d.idx)}
          />
        ))}
        <Line
          dataKey="xt"
          type="monotone"
          stroke="var(--color-xt)"
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartContainer>
  )
}
