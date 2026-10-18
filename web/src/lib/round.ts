// Python rounds exact ties to even (round(0.5) == 0, f"{0.0625:.3f}" == "0.062"); JavaScript's toFixed
// rounds them away from zero. Numbers shown here must match the engine's to the digit, so ties are found
// on the double's exact decimal expansion: x * 10 ** digits can land on .5 when x itself is not a tie.

/** Python's f"{x:.{digits}f}". */
export function toFixed(x: number, digits: number): string {
  const exact = Math.abs(x).toFixed(100)
  const point = exact.indexOf(".")
  const rest = exact.slice(point + 1 + digits)
  if (rest[0] !== "5" || /[1-9]/.test(rest.slice(1))) return x.toFixed(digits)
  const kept = exact.slice(0, point + 1 + digits).replace(/\.$/, "")
  const even = Number(kept.at(-1)) % 2 === 0
  const magnitude = even ? Number(kept) : Number(kept) + 10 ** -digits
  return (x < 0 ? -magnitude : magnitude).toFixed(digits)
}

/** Python's round(x, digits). */
export function roundTo(x: number, digits = 0): number {
  return Number(toFixed(x, digits))
}
