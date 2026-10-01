/** Presentation only: lifecycle enums, evidence and readiness stay authoritative. */
export function closeOwnerCopy(text: string): string {
  return text
    .replaceAll("в core-контракте", "в сохранённых данных")
    .replaceAll("из действующего Close Cockpit", "по текущей проверке готовности")
    .replaceAll("Close Cockpit", "Проверка готовности")
    .replaceAll("hard blockers", "блокеров")
    .replaceAll("hard blocker", "блокер")
    .replaceAll("этим read model", "по сохранённым данным")
    .replaceAll("командой Close", "действием «Закрыть месяц»")
    .replaceAll(
      "Outlook появляется только после закрытия и отдельной композиции известных событий.",
      "События следующего месяца доступны после закрытия, по известным датам.",
    )
    .replaceAll("provenance", "происхождение данных");
}
