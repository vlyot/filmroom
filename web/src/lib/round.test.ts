import { describe, expect, it } from "vitest"

import { roundTo, toFixed } from "@/lib/round"

describe("round", () => {
  it("rounds exact ties to even, as Python does", () => {
    expect(roundTo(0.5)).toBe(0)
    expect(roundTo(1.5)).toBe(2)
    expect(roundTo(2.5)).toBe(2)
    expect(toFixed(0.0625, 3)).toBe("0.062")
    expect(toFixed(0.03125, 4)).toBe("0.0312")
    expect(toFixed(-0.0625, 3)).toBe("-0.062")
  })

  it("rounds values that only look like ties to the nearest", () => {
    expect(toFixed(0.0255, 3)).toBe("0.025") // the double is just below 0.0255
    expect(toFixed(12.6, 0)).toBe("13")
    expect(roundTo(0.1234567, 6)).toBe(0.123457)
  })
})
