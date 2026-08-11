import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { formatApiError } from "../api/client";
import {
  getTaxBrackets,
  updateTaxBrackets,
  type TaxBracketRule,
  type TaxBracketYearConfig,
} from "../api/taxBrackets";
import { normalizeMoneyInput, rub, toKopecks } from "../lib/money";
import { Badge, Button, Field, Input, Panel, Table, Td, Th } from "./ui";

type EditableBracket = {
  id: string;
  to: string;
  rate: string;
};

let nextRowId = 0;

function editableBracket(to: string, rate: string): EditableBracket {
  nextRowId += 1;
  return { id: `tax-bracket-row-${nextRowId}`, to, rate };
}

const MONTH_NAMES = [
  "январь",
  "февраль",
  "март",
  "апрель",
  "май",
  "июнь",
  "июль",
  "август",
  "сентябрь",
  "октябрь",
  "ноябрь",
  "декабрь",
] as const;

function rateBpsToPercent(rateBps: number): string {
  const whole = Math.trunc(rateBps / 100);
  const fraction = rateBps % 100;
  if (fraction === 0) return String(whole);
  return `${whole}.${String(fraction).padStart(2, "0").replace(/0$/, "")}`;
}

function percentToRateBps(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  const match = /^(\d{1,3})(?:\.(\d{1,2}))?$/.exec(normalized);
  if (!match) return null;
  const fraction = (match[2] ?? "").padEnd(2, "0");
  const bps = BigInt(match[1]) * 100n + BigInt(fraction || "0");
  if (bps > 10_000n) return null;
  return Number(bps);
}

function monthCodeLabel(code: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(code);
  if (!match) return code;
  const monthName = MONTH_NAMES[Number(match[2]) - 1];
  return monthName ? `${monthName} ${match[1]}` : code;
}

function rowsFromConfig(config: TaxBracketYearConfig): EditableBracket[] {
  return config.brackets.map((bracket) =>
    editableBracket(bracket.threshold_to?.amount ?? "", rateBpsToPercent(bracket.rate_bps)),
  );
}

function sourceLabel(source: TaxBracketYearConfig["source"]): string {
  return source === "official_default" ? "Официальная шкала" : "Пользовательская шкала";
}

export function TaxBracketsPanel() {
  const currentYear = new Date().getFullYear();
  const [yearInput, setYearInput] = useState(String(currentYear));
  const [config, setConfig] = useState<TaxBracketYearConfig | null>(null);
  const [rows, setRows] = useState<EditableBracket[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const selectedYear = Number(yearInput);
  const validYear = Number.isInteger(selectedYear) && selectedYear >= 2000 && selectedYear <= 2100;

  const load = useCallback(async (year: number, signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const loaded = await getTaxBrackets(year, signal);
      if (signal?.aborted) return;
      setConfig(loaded);
      setRows(rowsFromConfig(loaded));
    } catch (loadError) {
      if (!signal?.aborted) {
        setConfig(null);
        setRows([]);
        setError(formatApiError(loadError));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(currentYear, controller.signal);
    return () => controller.abort();
  }, [currentYear, load]);

  const lowerBounds = useMemo(() => {
    const bounds = ["0.00"];
    for (let index = 1; index < rows.length; index += 1) {
      bounds.push(rows[index - 1].to || "…");
    }
    return bounds;
  }, [rows]);

  async function handleLoadYear() {
    if (!validYear || loading || saving) {
      if (!validYear) setError("Укажи год от 2000 до 2100.");
      return;
    }
    await load(selectedYear);
  }

  function addBracket() {
    if (!config?.mutable || rows.length === 0) return;
    setRows((current) => {
      const last = current[current.length - 1];
      return [...current.slice(0, -1), editableBracket("", last.rate), last];
    });
    setSuccess(null);
    setError(null);
  }

  function removeBracket(index: number) {
    if (!config?.mutable || rows.length <= 1) return;
    setRows((current) => {
      const next = current.filter((_, rowIndex) => rowIndex !== index);
      const lastIndex = next.length - 1;
      next[lastIndex] = { ...next[lastIndex], to: "" };
      return next;
    });
    setSuccess(null);
    setError(null);
  }

  function buildPayload(): TaxBracketRule[] | null {
    if (rows.length === 0) {
      setError("Должна остаться хотя бы одна налоговая ступень.");
      return null;
    }

    const result: TaxBracketRule[] = [];
    let lower = "0.00";
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index];
      const rateBps = percentToRateBps(row.rate);
      if (rateBps == null) {
        setError(`Ступень ${index + 1}: ставка должна быть от 0 до 100% с точностью до 0,01%.`);
        return null;
      }

      const isLast = index === rows.length - 1;
      let upper: string | null = null;
      if (!isLast) {
        upper = normalizeMoneyInput(row.to);
        if (upper == null || toKopecks(upper) <= toKopecks(lower)) {
          setError(`Ступень ${index + 1}: верхняя граница должна быть больше нижней.`);
          return null;
        }
      }

      result.push({
        threshold_from: rub(lower),
        threshold_to: upper == null ? null : rub(upper),
        rate_bps: rateBps,
      });
      if (upper != null) lower = upper;
    }
    return result;
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    if (!config?.mutable || saving) return;
    const brackets = buildPayload();
    if (!brackets) return;

    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const saved = await updateTaxBrackets(config.year, { brackets });
      setConfig(saved);
      setRows(rowsFromConfig(saved));
      setSuccess("Налоговые ступени сохранены.");
    } catch (saveError) {
      setError(formatApiError(saveError));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel label="НДФЛ" title="Налоговые ступени">
      <div className="stack-18">
        <div className="form-row-2">
          <Field htmlFor="tax-brackets-year" label="Налоговый год">
            <Input
              id="tax-brackets-year"
              inputMode="numeric"
              max="2100"
              min="2000"
              onChange={(event) => {
                setYearInput(event.target.value);
                setSuccess(null);
              }}
              type="number"
              value={yearInput}
            />
          </Field>
          <div className="field">
            <span className="field__label">Период действия</span>
            <p>{config ? `01.01.${config.year} — 31.12.${config.year}` : "—"}</p>
            <Button disabled={!validYear || loading || saving} onClick={() => void handleLoadYear()}>
              {loading ? "Загружаем…" : "Открыть год"}
            </Button>
          </div>
        </div>

        {config ? (
          <>
            <div className="stack-8">
              <p>
                <Badge tone={config.source === "official_default" ? "info" : "neutral"}>
                  {sourceLabel(config.source)}
                </Badge>{" "}
                <Badge tone={config.mutable ? "ok" : "closed"}>
                  {config.mutable ? "Можно редактировать" : "Год зафиксирован"}
                </Badge>
              </p>
              {config.mutable ? (
                <p className="muted">
                  Сохраняется вся шкала целиком. Нижняя граница каждой следующей ступени совпадает с
                  верхней границей предыдущей.
                </p>
              ) : (
                <p className="inline-alert inline-alert--info">
                  Ставки нельзя менять, пока в этом году есть закрытые месяцы: {" "}
                  {config.closed_months.map(monthCodeLabel).join(", ")}. Чтобы намеренно пересчитать
                  историю, сначала открой все закрытые месяцы этого года.
                </p>
              )}
            </div>

            <form className="stack-18" onSubmit={handleSave}>
              <Table>
                <thead>
                  <tr>
                    <Th>От, ₽</Th>
                    <Th>До, ₽</Th>
                    <Th>Ставка, %</Th>
                    <Th>Действия</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => {
                    const isLast = index === rows.length - 1;
                    return (
                      <tr key={row.id}>
                        <Td>{lowerBounds[index]}</Td>
                        <Td>
                          {isLast ? (
                            "Без верхней границы"
                          ) : (
                            <Input
                              aria-label={`Верхняя граница ступени ${index + 1}`}
                              disabled={!config.mutable}
                              onChange={(event) => {
                                const value = event.target.value;
                                setRows((current) =>
                                  current.map((item, rowIndex) =>
                                    rowIndex === index ? { ...item, to: value } : item,
                                  ),
                                );
                                setSuccess(null);
                              }}
                              value={row.to}
                            />
                          )}
                        </Td>
                        <Td>
                          <Input
                            aria-label={`Ставка ступени ${index + 1}`}
                            disabled={!config.mutable}
                            onChange={(event) => {
                              const value = event.target.value;
                              setRows((current) =>
                                current.map((item, rowIndex) =>
                                  rowIndex === index ? { ...item, rate: value } : item,
                                ),
                              );
                              setSuccess(null);
                            }}
                            value={row.rate}
                          />
                        </Td>
                        <Td>
                          <Button
                            disabled={!config.mutable || rows.length <= 1}
                            onClick={() => removeBracket(index)}
                            type="button"
                            variant="danger"
                          >
                            Удалить
                          </Button>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>

              {config.mutable ? (
                <div className="button-row">
                  <Button onClick={addBracket} type="button">
                    Добавить ступень
                  </Button>
                  <Button disabled={saving} type="submit" variant="primary">
                    {saving ? "Сохраняем…" : "Сохранить налоговые ступени"}
                  </Button>
                </div>
              ) : null}
            </form>
          </>
        ) : null}

        {error ? (
          <div className="inline-alert inline-alert--error" role="alert">
            {error}
          </div>
        ) : null}
        {success ? (
          <div className="inline-alert inline-alert--ok" role="status">
            {success}
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
