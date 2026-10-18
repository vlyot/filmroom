// The engine's expected output for the browser ports (contracts/parity.json, written by tests/web_parity.py).
import data from "@contracts/parity.json"

import type {
  Fact,
  Match,
  Possession,
  StyleConfig,
  StyleLens,
  Verdict,
} from "@/contracts"

export type ParityCase = {
  possession_id: string
  style: StyleConfig
  verdict: Verdict
  facts: Record<string, Record<string, Fact>>
  narratives: Record<
    string,
    { template: string; claims: unknown[]; text: string }
  >
}

export const golden = data as unknown as {
  lens: StyleLens
  styles: StyleConfig[]
  match: Match
  possessions: Possession[]
  cases: ParityCase[]
  formats: { fact: Fact; language: string; text: string }[]
}
