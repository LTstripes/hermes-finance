import { fromKopecks } from "./money";

/** Decimal ROUND_HALF_UP to two percentage decimals; never coerce the value to Number. */
export function formatSourceReturnRate(value: string | null | undefined, fraction = true): string {
  if (value == null) return "—";
  const match = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d{1,3}))?$/.exec(value);
  if (!match) return "—";
  const digits = match[2] + (match[3] ?? "");
  // Only the bounded decimal-point position is numeric, never the financial value.
  const point = match[2].length + Number(match[4] ?? 0) + (fraction ? 4 : 2);
  let hundredths = point > 0 ? BigInt(digits.slice(0, point).padEnd(point, "0")) : 0n;
  const discarded = point >= 0 ? digits[point] : undefined;
  if (discarded !== undefined && discarded >= "5") hundredths += 1n;
  // Round the magnitude, then restore its sign: ties go away from zero, including carry.
  return `${match[1] ? "−" : ""}${fromKopecks(hundredths).replace(".", ",")}%`;
}
