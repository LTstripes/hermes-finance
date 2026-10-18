import { useEffect, useRef, useState } from "react";
import {
  lookupPublicIdentities,
  type BrokerMonthPreview,
  type InstrumentDecision,
} from "../../api/brokerMonths";
import { formatApiError } from "../../api/client";
import { Button, Table, Td, Th } from "../ui";
import styles from "./BrokerMonthReview.module.css";
import { useBrokerOriginalSession } from "./brokerOriginalSession";

export function SourceIdentityInbox({
  preview,
  disabled,
  onReview,
}: {
  preview: BrokerMonthPreview;
  disabled: boolean;
  onReview: (decisions: InstrumentDecision[]) => void;
}) {
  const { session, original } = useBrokerOriginalSession();
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [looking, setLooking] = useState(false);
  const request = useRef(0);
  const instruments = preview.identity?.instruments ?? [];
  const pending = instruments.filter((i) => i.intake_status === "pending_review");
  const matched = instruments.filter((i) => i.intake_status === "matched");
  const needed = [
    ...new Set(
      pending
        .filter((i) => i.hermes_id == null && /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/.test(i.isin))
        .map((i) => i.isin),
    ),
  ].filter((isin) => !original.publicResults.some((r) => r.isin === isin));
  const lookupKey = needed.join(",");
  useEffect(() => {
    if (!original.lookupConsent || !lookupKey || disabled) return;
    const epoch = original.epoch;
    const version = ++request.current;
    const abort = new AbortController();
    setLooking(true);
    setError(null);
    void (async () => {
      try {
        const results = [];
        const isins = lookupKey.split(",");
        for (let index = 0; index < isins.length; index += 32) {
          const batch = await lookupPublicIdentities(isins.slice(index, index + 32), abort.signal);
          if (abort.signal.aborted || session.snapshot().epoch !== epoch) return;
          results.push(...batch);
        }
        if (version === request.current && !abort.signal.aborted) session.publicMetadata(results);
      } catch (e) {
        if (!abort.signal.aborted && version === request.current) setError(formatApiError(e));
      } finally {
        if (!abort.signal.aborted && version === request.current) setLooking(false);
      }
    })();
    return () => {
      abort.abort();
      setLooking(false);
    };
  }, [lookupKey, original.lookupConsent, original.epoch, disabled, session]);
  if (!preview.identity) return null;
  function review() {
    const decisions = new Map((preview.instrument_decisions ?? []).map((d) => [d.isin, d]));
    for (const [isin, choice] of Object.entries(choices)) {
      if (choice.startsWith("official:")) decisions.set(isin, { isin, proof_id: choice.slice(9) });
      else if (choice.startsWith("card:"))
        decisions.set(isin, { isin, hermes_id: Number(choice.slice(5)) });
      else decisions.delete(isin);
    }
    onReview([...decisions.values()]);
  }
  return (
    <section aria-label="Очередь identity источника" className={styles.stack}>
      <p>
        Исходные кандидаты: MATCHED — {matched.length}; PENDING REVIEW — {pending.length}. Разобраны
        все строки оригинала. Это ещё не принятый финансовый DRAFT.
      </p>
      <p>
        Unsupported financial evidence — {preview.exceptions.length}. Доказательства Money и Close
        проверяются отдельно.
      </p>
      {pending.length > 0 || original.lookupConsent ? (
        <label className={styles.review}>
          <input
            type="checkbox"
            checked={original.lookupConsent}
            disabled={disabled}
            onChange={(e) => session.consent(e.target.checked)}
          />{" "}
          Разрешаю автоматический поиск публичных ISIN в MOEX ISS для этой сессии
        </label>
      ) : null}
      <p>
        Наружу уходят только ISIN/SECID. Оригинал, имя файла, счета, суммы и количества не
        передаются. Разрешение можно отозвать; новые запросы прекратятся.
      </p>
      {looking ? <p role="status">Ищем публичные варианты до ручного разбора…</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {pending.length && original.lookupConsent && !looking ? (
        <Button
          type="button"
          disabled={disabled}
          onClick={() => {
            session.refreshPublic();
            onReview([]);
          }}
        >
          Обновить публичные варианты и Preview
        </Button>
      ) : null}
      <details>
        <summary>Все сопоставленные бумаги ({matched.length})</summary>
        <ul>
          {matched.map((i) => (
            <li key={i.isin}>
              {i.source_name} · {i.isin} · {i.instrument_type} · {i.currency ?? "UNKNOWN"} · MATCHED
              {i.hermes_id == null
                ? " — подтверждённое предложение создания"
                : ` · #${i.hermes_id}`}
            </li>
          ))}
        </ul>
      </details>
      {pending.length ? (
        <>
          <p>
            Одна очередь оставшихся исключений. Отложенные строки остаются видимыми и блокируют
            DRAFT всего оригинала.
          </p>
          <Table aria-label="Ручная очередь identity">
            <thead>
              <tr>
                <Th>Бумага источника</Th>
                <Th>Причины</Th>
                <Th>Варианты с доказательствами</Th>
              </tr>
            </thead>
            <tbody>
              {pending.map((item) => {
                const official = original.publicResults.find((r) => r.isin === item.isin);
                return (
                  <tr key={item.isin}>
                    <Td>
                      {item.source_name ?? "Имя неизвестно"}
                      <br />
                      {item.isin} · {item.instrument_type ?? "UNKNOWN"}
                      <br />
                      Строки:{" "}
                      {item.observations?.map((r) => `${r.section} #${r.ordinal + 1}`).join(", ")}
                    </Td>
                    <Td>
                      {item.review_reasons?.join(", ")}
                      {official?.reasons.length ? <p>{official.reasons.join(", ")}</p> : null}
                    </Td>
                    <Td>
                      <label className={styles.field}>
                        Решение для {item.isin}
                        <select
                          value={choices[item.isin] ?? ""}
                          disabled={disabled || looking}
                          onChange={(e) =>
                            setChoices((prior) => ({ ...prior, [item.isin]: e.target.value }))
                          }
                        >
                          <option value="">Отложить — оставить PENDING REVIEW</option>
                          {item.candidates?.map((c) => (
                            <option
                              key={c.hermes_id}
                              value={`card:${c.hermes_id}`}
                              disabled={c.reasons.length > 0}
                            >
                              #{c.hermes_id} {c.name} · {c.isin ?? "NULL-ISIN"} ·{" "}
                              {c.currency ?? "UNKNOWN"} {c.reasons.join(", ")}
                            </option>
                          ))}
                          {official?.candidates.map((c) => (
                            <option
                              key={c.secid}
                              value={`official:${official.proof_id}`}
                              disabled={
                                official.reasons.length > 0 ||
                                c.reasons.length > 0 ||
                                c.instrument_type !== item.instrument_type ||
                                c.currency !== "RUB" ||
                                new Date(official.expires_at).getTime() <= Date.now()
                              }
                            >
                              Создать: {c.name} · {c.secid} · {c.currency ?? "UNKNOWN"}{" "}
                              {c.reasons.join(", ")}{" "}
                              {c.currency && c.currency !== "RUB"
                                ? "instrument_currency_unsupported"
                                : ""}
                            </option>
                          ))}
                        </select>
                      </label>
                      {official?.candidates.map((c) => (
                        <p key={c.secid}>
                          <a href={c.url} target="_blank" rel="noreferrer">
                            MOEX: {c.secid}
                          </a>{" "}
                          · {official.retrieved_at} · {c.reasons.join(", ")}
                        </p>
                      ))}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          <Button
            type="button"
            disabled={disabled || looking || !Object.values(choices).some(Boolean)}
            onClick={review}
          >
            Подтвердить решения и заново проверить весь оригинал
          </Button>
        </>
      ) : null}
    </section>
  );
}
