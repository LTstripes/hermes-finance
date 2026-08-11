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
    return (
      <div className="field">
        <span className="field__label">Ставка НДФЛ</span>
        <strong>—</strong>
      </div>
    );
  }

  const marginalRate = rates[rates.length - 1];
  const marginalLabel = formatRateBps(marginalRate);

  if (rates.length === 1) {
    return (
      <div className="field">
        <span className="field__label">Текущая ставка НДФЛ</span>
        <strong>{marginalLabel}</strong>
        <span className="muted tiny">По расчёту backend для этой выплаты.</span>
      </div>
    );
  }

  const applied = rates.map(formatRateBps).join(" + ");
  return (
    <div className="field">
      <span className="field__label">Ставки НДФЛ в этой выплате</span>
      <strong>{applied}</strong>
      <span className="muted tiny">Текущая ступень после выплаты: {marginalLabel}.</span>
    </div>
  );
}
