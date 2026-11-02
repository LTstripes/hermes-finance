import { reasonCopy } from "./reasonCopy";
import type { CloseReadinessItem } from "../api/types";

type ReadinessCopy = {
  title: string;
  message: string;
};

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

export function readinessCopy(item: CloseReadinessItem): ReadinessCopy {
  return {
    title: reasonCopy(item.code, { surface: "readinessTitle" }).message,
    message: reasonCopy(item.code, { surface: "readiness" }).message,
  };
}

export function readinessDiagnostic(item: CloseReadinessItem): string {
  const context =
    Object.keys(item.context).length > 0 ? JSON.stringify(item.context, null, 2) : "нет";
  return `Код: ${item.code}\nСерверное сообщение: ${item.message}\nКонтекст: ${context}`;
}

export function russianCount(count: number, one: string, few: string, many: string): string {
  const moduloTen = count % 10;
  const moduloHundred = count % 100;
  const form =
    moduloTen === 1 && moduloHundred !== 11
      ? one
      : moduloTen >= 2 && moduloTen <= 4 && (moduloHundred < 12 || moduloHundred > 14)
        ? few
        : many;
  return `${count} ${form}`;
}
