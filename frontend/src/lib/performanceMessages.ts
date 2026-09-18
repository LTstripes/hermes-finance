/**
 * Owner-facing copy for the supported portfolio performance read models.
 *
 * The raw backend reason codes stay behind the disclosure; these messages are
 * the same ones the current Analytics surface already shows, so Home-style and
 * Capital-style surfaces cannot drift apart.
 */

export const VALUE_BRIDGE_LABEL = "Изменение стоимости после внешних потоков";
export const VALUE_BRIDGE_DISCLAIMER = "Это изменение стоимости, а не доходность.";

export function portfolioXirrUnavailableMessage(reasonCodes: string[]): string {
  if (reasonCodes.some((code) => code.includes("valuation"))) {
    return "Расчёт недоступен: нет полного набора подтверждённых оценок на границах периода.";
  }
  if (reasonCodes.some((code) => code.includes("flow"))) {
    return "Расчёт недоступен: история внешних пополнений и снятий неполна.";
  }
  if (reasonCodes.some((code) => code.includes("root"))) {
    return "Расчёт недоступен: однозначность корня для этой истории не подтверждена.";
  }
  if (reasonCodes.some((code) => code.includes("membership") || code.includes("scope"))) {
    return "Расчёт недоступен: не подтверждён состав портфеля на всём периоде.";
  }
  return "Расчёт недоступен: не удалось подтвердить достаточность данных для XIRR.";
}

export function portfolioTwrrUnavailableMessage(reasonCodes: string[]): string {
  if (reasonCodes.some((code) => code.includes("valuation_boundary"))) {
    return "Расчёт недоступен: не подтверждены наблюдения до и после внешних операций.";
  }
  if (reasonCodes.some((code) => code.includes("flow"))) {
    return "Расчёт недоступен: история внешних пополнений и снятий неполна.";
  }
  if (reasonCodes.some((code) => code.includes("denominator"))) {
    return "Расчёт недоступен: один из периодов не имеет положительной базы расчёта.";
  }
  if (reasonCodes.some((code) => code.includes("membership") || code.includes("scope"))) {
    return "Расчёт недоступен: не подтверждён состав портфеля на всём периоде.";
  }
  return "Расчёт недоступен: не удалось подтвердить достаточность данных для TWRR.";
}

export function performanceAttributionUnavailableMessage(reasonCodes: string[]): string {
  if (reasonCodes.some((code) => code.includes("valuation"))) {
    return "Не подтверждены оценки стоимости на границах выбранного периода.";
  }
  if (reasonCodes.some((code) => code.includes("flow"))) {
    return "История внешних пополнений и выводов за период неполна.";
  }
  if (reasonCodes.some((code) => code.includes("in_kind"))) {
    return "Данные по неденежным перемещениям за период неполны.";
  }
  if (reasonCodes.some((code) => code.includes("currency"))) {
    return "Не подтверждена единая валюта изменения стоимости за период.";
  }
  if (reasonCodes.some((code) => code.includes("membership") || code.includes("scope"))) {
    return "Не подтверждён состав портфеля на всём выбранном периоде.";
  }
  if (reasonCodes.some((code) => code.includes("transfer"))) {
    return "Не подтверждено внутреннее перемещение между счетами за период.";
  }
  return "Недостаточно подтверждённых данных для точного изменения стоимости.";
}
