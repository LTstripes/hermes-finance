import type { Instrument } from "../api/types";

/** Remove only known identity suffixes; preserve the instrument's actual name. */
export function shortInstrumentName(
  instrument: Pick<Instrument, "name" | "ticker" | "isin">,
): string {
  let name = instrument.name.trim();
  const identities = [instrument.ticker, instrument.isin].filter(Boolean);
  let previous = "";
  while (name !== previous) {
    previous = name;
    for (const identity of identities) {
      const suffix = `(${identity})`;
      if (name.endsWith(suffix)) name = name.slice(0, -suffix.length).trimEnd();
    }
  }
  return name || instrument.isin || instrument.ticker || "Без названия";
}
