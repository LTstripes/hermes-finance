const NBSP = "\u00a0";
const MONTHS_RU = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
] as const;

const moneyGroupRe = /\B(?=(\d{3})+(?!\d))/g;

/** Group integer digits with non-breaking spaces: 1234567 → 1 234 567 */
function groupInteger(digits: string): string {
  return digits.replace(moneyGroupRe, NBSP);
}

/**
 * Format money major units for display.
 * Accepts a decimal string (preferred) — no binary float math.
 * Whole rubles: "1234567" → "1 234 567 ₽"
 * With cents: "1234.5" → "1 234,50 ₽"
 */
export function formatMoney(
  major: string | null | undefined,
  options: { currency?: string; empty?: string } = {},
): string {
  const { currency = "₽", empty = "—" } = options;
  if (major == null || major.trim() === "") {
    return empty;
  }

  const raw = major.trim().replace(/\s/g, "").replace(",", ".");
  const negative = raw.startsWith("-");
  const unsigned = negative ? raw.slice(1) : raw;
  if (!/^\d+(\.\d+)?$/.test(unsigned)) {
    return empty;
  }

  const [intPart, fracPart] = unsigned.split(".");
  const grouped = groupInteger(intPart);
  let body = grouped;
  if (fracPart != null) {
    const cents = `${fracPart}00`.slice(0, 2);
    body = cents === "00" ? grouped : `${grouped},${cents}`;
  }

  const sign = negative ? "−" : "";
  return `${sign}${body}${NBSP}${currency}`;
}

/** Signed delta helper: "+1 200 ₽" / "−48 200 ₽" */
export function formatMoneyDelta(
  major: string | null | undefined,
  options: { currency?: string; empty?: string } = {},
): string {
  const { empty = "—" } = options;
  if (major == null || major.trim() === "") {
    return empty;
  }
  const raw = major.trim().replace(/\s/g, "").replace(",", ".");
  if (!/^-?\d+(\.\d+)?$/.test(raw)) {
    return empty;
  }
  if (
    raw === "0" ||
    raw === "0.0" ||
    raw === "0.00" ||
    raw === "-0" ||
    raw === "-0.0" ||
    raw === "-0.00"
  ) {
    return formatMoney("0", options);
  }
  const negative = raw.startsWith("-");
  const formatted = formatMoney(raw, options);
  if (formatted === empty) {
    return empty;
  }
  if (!negative) {
    return `+${formatted}`;
  }
  return formatted;
}

/**
 * Percent display, max 1–2 fraction digits.
 * Input is percentage points (e.g. "2.4" → "2,4%").
 */
export function formatPercent(
  value: string | number | null | undefined,
  options: { digits?: 1 | 2; empty?: string; signed?: boolean } = {},
): string {
  const { digits = 1, empty = "—", signed = false } = options;
  if (value == null || value === "") {
    return empty;
  }
  const raw = String(value).trim().replace(/\s/g, "").replace(",", ".");
  const negative = raw.startsWith("-");
  const unsigned = negative ? raw.slice(1) : raw;
  if (!/^\d+(\.\d+)?$/.test(unsigned)) {
    return empty;
  }
  const [intPart, frac = ""] = unsigned.split(".");
  const fracDigits = frac.padEnd(digits, "0").slice(0, digits);
  const body = `${intPart},${fracDigits}`;
  const sign = negative ? "−" : signed ? "+" : "";
  return `${sign}${body}%`;
}

/** Calendar date → ДД.ММ.ГГГГ */
export function formatDate(
  input: string | Date | null | undefined,
  options: { empty?: string } = {},
): string {
  const { empty = "—" } = options;
  if (input == null || input === "") {
    return empty;
  }

  let year: number;
  let month: number;
  let day: number;

  if (input instanceof Date) {
    if (Number.isNaN(input.getTime())) {
      return empty;
    }
    year = input.getFullYear();
    month = input.getMonth() + 1;
    day = input.getDate();
  } else {
    const iso = input.trim();
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    if (m) {
      year = Number(m[1]);
      month = Number(m[2]);
      day = Number(m[3]);
    } else {
      const parsed = new Date(iso);
      if (Number.isNaN(parsed.getTime())) {
        return empty;
      }
      year = parsed.getFullYear();
      month = parsed.getMonth() + 1;
      day = parsed.getDate();
    }
  }

  const dd = String(day).padStart(2, "0");
  const mm = String(month).padStart(2, "0");
  return `${dd}.${mm}.${year}`;
}

/** Month label: formatMonth(2026, 7) → "Июль 2026" */
export function formatMonth(year: number, month: number, options: { empty?: string } = {}): string {
  const { empty = "—" } = options;
  if (!Number.isInteger(year) || !Number.isInteger(month) || month < 1 || month > 12) {
    return empty;
  }
  return `${MONTHS_RU[month - 1]}${NBSP}${year}`;
}

/** Parse "YYYY-MM" → "Июль 2026" */
export function formatMonthKey(
  key: string | null | undefined,
  options: { empty?: string } = {},
): string {
  const { empty = "—" } = options;
  if (key == null || key.trim() === "") {
    return empty;
  }
  const m = /^(\d{4})-(\d{2})$/.exec(key.trim());
  if (!m) {
    return empty;
  }
  return formatMonth(Number(m[1]), Number(m[2]), options);
}

/** Ratio like coverage 0.68 → "0,68×" */
export function formatRatio(
  value: string | number | null | undefined,
  options: { digits?: 1 | 2; empty?: string } = {},
): string {
  const { digits = 2, empty = "—" } = options;
  if (value == null || value === "") {
    return empty;
  }
  const raw = String(value).trim().replace(/\s/g, "").replace(",", ".");
  if (!/^-?\d+(\.\d+)?$/.test(raw)) {
    return empty;
  }
  const negative = raw.startsWith("-");
  const unsigned = negative ? raw.slice(1) : raw;
  const [intPart, frac = ""] = unsigned.split(".");
  const fracDigits = frac.padEnd(digits, "0").slice(0, digits);
  const body = `${intPart},${fracDigits}`;
  return `${negative ? "−" : ""}${body}×`;
}
