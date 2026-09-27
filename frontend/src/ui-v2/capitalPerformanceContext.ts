import type { PerformanceReadinessScope } from "../api/types";

export type PerformanceDetailView = "accounts" | "classes";

export type PerformanceContext = {
  start: string;
  end: string;
  scope: PerformanceReadinessScope;
  accountId: number | null;
  view: PerformanceDetailView;
};

export type PerformanceContextError = {
  code:
    | "missing_interval"
    | "partial_interval"
    | "malformed_date"
    | "equal_dates"
    | "reversed_interval"
    | "missing_account"
    | "portfolio_account_mismatch"
    | "unknown_account";
  message: string;
};

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isValidIsoDate(value: string): boolean {
  if (!ISO_DATE_RE.test(value)) return false;
  const [y, m, d] = value.split("-").map(Number);
  if (m < 1 || m > 12 || d < 1 || d > 31) return false;
  const utc = Date.UTC(y, m - 1, d);
  const check = new Date(utc);
  return check.getUTCFullYear() === y && check.getUTCMonth() === m - 1 && check.getUTCDate() === d;
}

/**
 * Validate the leaf detail context. Malformed/partial/equal/reversed intervals
 * and scope/account mismatches are context errors, never silent defaults.
 * Unknown/deleted accounts are reported by the caller via `accountExists`.
 */
export function parsePerformanceContext(
  params: URLSearchParams,
  options: { accountExists?: (id: number) => boolean } = {},
):
  | { context: PerformanceContext; error: null }
  | { context: null; error: PerformanceContextError } {
  const start = params.get("start");
  const end = params.get("end");
  const scopeRaw = params.get("scope");
  const accountRaw = params.get("account_id");
  const viewRaw = params.get("view");

  const scope: PerformanceReadinessScope = scopeRaw === "account" ? "account" : "portfolio";
  const view: PerformanceDetailView = viewRaw === "classes" ? "classes" : "accounts";

  if (start === null && end === null) {
    return {
      context: null,
      error: {
        code: "missing_interval",
        message: "Выберите начальную и конечную даты снимков для расчёта доходности.",
      },
    };
  }
  if (start === null || end === null) {
    return {
      context: null,
      error: {
        code: "partial_interval",
        message: "Заданы не обе даты интервала: нужны и начальная, и конечная даты.",
      },
    };
  }
  if (!isValidIsoDate(start) || !isValidIsoDate(end)) {
    return {
      context: null,
      error: {
        code: "malformed_date",
        message: "Дата интервала задана неверно: используйте формат ГГГГ-ММ-ДД.",
      },
    };
  }
  if (start === end) {
    return {
      context: null,
      error: {
        code: "equal_dates",
        message: "Начальная и конечная даты совпадают: для доходности нужны две разные даты.",
      },
    };
  }
  if (start > end) {
    return {
      context: null,
      error: {
        code: "reversed_interval",
        message: "Начальная дата позже конечной: поменяйте даты местами.",
      },
    };
  }

  if (scope === "account") {
    if (accountRaw === null || accountRaw.trim() === "") {
      return {
        context: null,
        error: {
          code: "missing_account",
          message: "Для охвата «счёт» выберите конкретный счёт.",
        },
      };
    }
    if (!/^\d+$/.test(accountRaw.trim())) {
      return {
        context: null,
        error: {
          code: "missing_account",
          message: "Счёт задан неверно: нужен числовой идентификатор счёта.",
        },
      };
    }
    const accountId = Number(accountRaw.trim());
    if (options.accountExists !== undefined && !options.accountExists(accountId)) {
      return {
        context: null,
        error: {
          code: "unknown_account",
          message:
            "Выбранный счёт недоступен: он удалён или неизвестен. Портфель не подставляется.",
        },
      };
    }
    return { context: { start, end, scope, accountId, view }, error: null };
  }

  if (accountRaw !== null && accountRaw.trim() !== "") {
    return {
      context: null,
      error: {
        code: "portfolio_account_mismatch",
        message:
          "Охват «портфель» не сочетается со счётом: уберите счёт или выберите охват «счёт».",
      },
    };
  }
  return { context: { start, end, scope, accountId: null, view }, error: null };
}

export const PERFORMANCE_DETAIL_PATH = "/v2/capital/performance";

/** Deep link that preserves the full leaf context for back/refresh. */
export function performanceDetailHref(context: PerformanceContext): string {
  const query = new URLSearchParams({
    start: context.start,
    end: context.end,
    scope: context.scope,
  });
  if (context.scope === "account" && context.accountId !== null) {
    query.set("account_id", String(context.accountId));
  }
  if (context.view === "classes") {
    query.set("view", "classes");
  }
  return `${PERFORMANCE_DETAIL_PATH}?${query.toString()}`;
}

/** Calendar day count between two ISO dates (presentation only, not a return calculation). */
export function intervalDays(start: string, end: string): number | null {
  if (!isValidIsoDate(start) || !isValidIsoDate(end)) return null;
  const [sy, sm, sd] = start.split("-").map(Number);
  const [ey, em, ed] = end.split("-").map(Number);
  const diff = Date.UTC(ey, em - 1, ed) - Date.UTC(sy, sm - 1, sd);
  return Math.round(diff / 86_400_000);
}

/** Short-history annualization warning is presentation-only, never a value change. */
export function needsAnnualizationWarning(start: string, end: string): boolean {
  const days = intervalDays(start, end);
  return days !== null && days < 365;
}

/** Exact zero in percentage points (string decimal, no float math). */
export function isZeroPercent(value: string | null): boolean {
  if (value === null) return false;
  return /^-?0+(\.0+)?$/.test(value.trim());
}

/** One interval↔calendar preset target (presentation only; exact-date match required). */
export function shiftCalendarBack(endIso: string, months: number): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(endIso);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const total = mo - 1 - months;
  const norm = ((total % 12) + 12) % 12;
  const targetYear = y + Math.floor(total / 12);
  const targetMonth = norm + 1;
  const lastDay = new Date(Date.UTC(targetYear, targetMonth, 0)).getUTCDate();
  const endMonthLast = new Date(Date.UTC(y, mo, 0)).getUTCDate();
  const keepEndOfMonth = d >= endMonthLast;
  const day = keepEndOfMonth ? lastDay : Math.min(d, lastDay);
  const mm = String(targetMonth).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return `${targetYear}-${mm}-${dd}`;
}
