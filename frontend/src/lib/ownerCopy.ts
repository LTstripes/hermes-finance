import { reasonCopy } from "./reasonCopy";
export function brokerSourceTitle(code: string): string | null {
  return reasonCopy(code, { surface: "brokerSource" }).message;
}

export function currencyProvenanceTitle(basis: string) {
  const titles: Record<string, string> = {
    owner_default_rub: "RUB — допущение Owner",
    owner_selected: "Выбрано Owner",
    source_proven: "Подтверждено источником",
    official_proven: "Официальное подтверждение",
    existing_catalogue: "Из принятого каталога",
    conflict: "Противоречие",
    unknown: "Не подтверждено",
  };
  return titles[basis] ?? "Не подтверждено";
}
