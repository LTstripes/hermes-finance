import { reasonCopy } from "./reasonCopy";
export const VALUE_BRIDGE_LABEL = "Изменение стоимости после внешних потоков";
export const VALUE_BRIDGE_DISCLAIMER = "Это изменение стоимости, а не доходность.";
export function portfolioXirrUnavailableMessage(reasonCodes: string[]): string {
  return reasonCopy(reasonCodes[0], { surface: "xirr" }).message;
}
export function portfolioTwrrUnavailableMessage(reasonCodes: string[]): string {
  return reasonCopy(reasonCodes[0], { surface: "twrr" }).message;
}
export function performanceAttributionUnavailableMessage(reasonCodes: string[]): string {
  return reasonCopy(reasonCodes[0], { surface: "attribution" }).message;
}
