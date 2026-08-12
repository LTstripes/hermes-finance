import { DataValue } from "./ui";

type SalaryTaxRatePart = {
  rate_bps: number;
};

function formatRateBps(rateBps: number): string {
  const whole = Math.trunc(rateBps / 100);
  const remainder = Math.abs(rateBps % 100);
  return remainder === 0 ? `${whole}%` : `${whole},${String(remainder).padStart(2, "0")}%`;
}

function uniqueRates(parts: SalaryTaxRatePart[]): number[] {
  const rates: number[] = [];
  for (const part of parts) {
    if (!rates.includes(part.rate_bps)) {
      rates.push(part.rate_bps);
    }
  }
  return rates;
}

export function SalaryTaxRateSummary({ parts }: { parts: SalaryTaxRatePart[] }) {
  const rates = uniqueRates(parts);
  if (rates.length === 0) {
    return <DataValue label="Ставка НДФЛ" value="—" muted />;
  }

  const marginalRate = rates[rates.length - 1];
  const marginalLabel = formatRateBps(marginalRate);

  if (rates.length === 1) {
    return (
      <DataValue
        label="Текущая ставка НДФЛ"
        meta="Применённая ступень для этой выплаты."
        value={marginalLabel}
      />
    );
  }

  const applied = rates.map(formatRateBps).join(" + ");
  return (
    <DataValue
      label="Ставки НДФЛ в этой выплате"
      meta={`Текущая ступень после выплаты: ${marginalLabel}.`}
      value={applied}
    />
  );
}
