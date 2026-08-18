import { type FormEvent, useEffect, useId, useState } from "react";

import type {
  Instrument,
  InstrumentMarketMapping,
  MarketDiscoverCandidate,
  MarketDiscoverResult,
  MarketIdentityWrite,
} from "../api/types";
import { labelOf } from "../lib/labels";
import {
  defaultMappingDraft,
  defaultMappingProvider,
  defaultTInvestDraft,
  formatDiscoverCandidateMeta,
  formatDiscoverCandidateTrade,
  formatMarketIdentity,
  identityToMoexDraft,
  identityToTInvestDraft,
  MAPPING_STATE_LABELS,
  MAPPING_SUPPORTED_TYPES,
  type MappingProviderId,
  MOEX_ISS_PROVIDER,
  type MoexMappingDraft,
  mappingStateTone,
  moexDraftToIdentity,
  T_INVEST_PROVIDER,
  type TInvestMappingDraft,
  tInvestDraftToIdentity,
} from "../lib/marketData";
import { Badge, Button, Field, Input } from "./ui";

type Props = {
  open: boolean;
  instrument: Instrument | null;
  mapping: InstrumentMarketMapping | null;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onSave: (payload: MarketIdentityWrite) => Promise<void>;
  onClear: () => Promise<void>;
  onExclude: () => Promise<void>;
  onClearExclusion: () => Promise<void>;
  onDiscover?: (
    provider: typeof T_INVEST_PROVIDER,
    query?: string | null,
  ) => Promise<MarketDiscoverResult>;
};

export function InstrumentMappingDialog({
  open,
  instrument,
  mapping,
  busy,
  error,
  onCancel,
  onSave,
  onClear,
  onExclude,
  onClearExclusion,
  onDiscover,
}: Props) {
  const titleId = useId();
  const descriptionId = useId();
  const [providerMode, setProviderMode] = useState<MappingProviderId>(T_INVEST_PROVIDER);
  const [moexDraft, setMoexDraft] = useState<MoexMappingDraft>(defaultMappingDraft("stock"));
  const [tInvestDraft, setTInvestDraft] = useState<TInvestMappingDraft>(defaultTInvestDraft());
  const [discoverQuery, setDiscoverQuery] = useState("");
  const [candidates, setCandidates] = useState<MarketDiscoverCandidate[]>([]);
  const [discoverMessage, setDiscoverMessage] = useState<string | null>(null);
  const [discoverBusy, setDiscoverBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !instrument) return;
    setProviderMode(defaultMappingProvider(mapping?.identity));
    setMoexDraft(identityToMoexDraft(mapping?.identity, instrument.instrument_type));
    setTInvestDraft(identityToTInvestDraft(mapping?.identity));
    setDiscoverQuery("");
    setCandidates([]);
    setDiscoverMessage(null);
    setLocalError(null);
  }, [open, instrument, mapping]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy && !discoverBusy) onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, discoverBusy, onCancel]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!open || !instrument) return null;

  const supported = MAPPING_SUPPORTED_TYPES.has(instrument.instrument_type);
  const state = mapping?.state ?? "unmapped";
  const hasIdentity = mapping?.identity != null;
  const formBusy = busy || discoverBusy;

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    let payload: MarketIdentityWrite;
    try {
      if (providerMode === T_INVEST_PROVIDER) {
        if (!tInvestDraft.providerInstrumentId.trim()) {
          setLocalError("Укажи идентификатор инструмента T-Invest или найди его по кнопке.");
          return;
        }
        payload = tInvestDraftToIdentity(tInvestDraft);
      } else {
        if (
          !moexDraft.provider.trim() ||
          !moexDraft.engine.trim() ||
          !moexDraft.market.trim() ||
          !moexDraft.boardid.trim() ||
          !moexDraft.secid.trim()
        ) {
          setLocalError("Заполни провайдер, движок, рынок, режим торгов и код бумаги.");
          return;
        }
        payload = moexDraftToIdentity(moexDraft);
      }
    } catch {
      setLocalError("Проверь введённые данные источника.");
      return;
    }
    setLocalError(null);
    await onSave(payload);
  }

  async function handleDiscover() {
    if (!onDiscover) return;
    setDiscoverBusy(true);
    setLocalError(null);
    setDiscoverMessage(null);
    try {
      const query = discoverQuery.trim();
      const result = await onDiscover(T_INVEST_PROVIDER, query || null);
      setCandidates(result.candidates);
      setDiscoverMessage(result.message);
      if (result.candidates.length === 0 && !result.message) {
        setDiscoverMessage("Подходящих инструментов T-Invest не найдено.");
      }
    } catch (caught) {
      setCandidates([]);
      setDiscoverMessage(
        caught instanceof Error ? caught.message : "Не удалось найти инструменты.",
      );
    } finally {
      setDiscoverBusy(false);
    }
  }

  function chooseCandidate(candidate: MarketDiscoverCandidate) {
    setTInvestDraft({
      provider: T_INVEST_PROVIDER,
      providerInstrumentId: candidate.provider_instrument_id,
      isin: candidate.isin,
    });
    setProviderMode(T_INVEST_PROVIDER);
    setLocalError(null);
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <div
        aria-describedby={descriptionId}
        aria-labelledby={titleId}
        aria-modal="true"
        className="dialog dialog--wide dialog--scroll"
        role="dialog"
      >
        <h2 className="dialog__title" id={titleId}>
          Источник котировки
        </h2>
        <p className="dialog__body" id={descriptionId}>
          Внешний источник задаётся явно. Подсказка из старого кода не считается принятым
          сопоставлением.
        </p>

        <div className="stack-8">
          <strong>{instrument.name}</strong>
          <div>
            <Badge tone={mappingStateTone(state)}>{labelOf(MAPPING_STATE_LABELS, state)}</Badge>
          </div>
          {hasIdentity && mapping?.identity ? (
            <p className="mapping-identity" data-testid="accepted-mapping-identity">
              {formatMarketIdentity(mapping.identity)}
            </p>
          ) : (
            <p className="muted tiny" data-testid="accepted-mapping-identity">
              Принятого источника нет.
            </p>
          )}
          {mapping?.instrument_isin ? (
            <p className="muted tiny">ISIN инструмента: {mapping.instrument_isin}</p>
          ) : null}
          {mapping?.legacy_moex_secid ? (
            <p className="muted tiny" data-testid="legacy-moex-hint">
              Старый код MOEX SECID: {mapping.legacy_moex_secid} — это не принятый источник.
            </p>
          ) : null}
        </div>

        {supported ? (
          <form className="form-stack" onSubmit={handleSave}>
            <div className="form-row-2">
              <Button
                disabled={formBusy}
                onClick={() => setProviderMode(T_INVEST_PROVIDER)}
                type="button"
                variant={providerMode === T_INVEST_PROVIDER ? "primary" : "secondary"}
              >
                T-Invest
              </Button>
              <Button
                disabled={formBusy}
                onClick={() => setProviderMode(MOEX_ISS_PROVIDER)}
                type="button"
                variant={providerMode === MOEX_ISS_PROVIDER ? "primary" : "secondary"}
              >
                MOEX ISS
              </Button>
            </div>

            {providerMode === T_INVEST_PROVIDER ? (
              <>
                <p className="muted tiny">
                  Production-источник 0.4. Режим торгов не нужен: канонический ключ —
                  instrument_uid.
                </p>
                {onDiscover ? (
                  <>
                    <Field htmlFor="mapping-t-invest-query" label="Название, тикер или ISIN">
                      <Input
                        id="mapping-t-invest-query"
                        onChange={(event) => {
                          setDiscoverQuery(event.target.value);
                          setCandidates([]);
                          setDiscoverMessage(null);
                        }}
                        placeholder="Например: SBER или RU0009029540"
                        value={discoverQuery}
                      />
                    </Field>
                    <p className="muted tiny">Поиск выполняется только после нажатия кнопки.</p>
                  </>
                ) : null}
                <Field htmlFor="mapping-t-invest-uid" label="Идентификатор инструмента T-Invest">
                  <Input
                    id="mapping-t-invest-uid"
                    onChange={(event) =>
                      setTInvestDraft((current) => ({
                        ...current,
                        providerInstrumentId: event.target.value,
                        isin: null,
                      }))
                    }
                    value={tInvestDraft.providerInstrumentId}
                  />
                </Field>
                {onDiscover ? (
                  <Button disabled={formBusy} onClick={() => void handleDiscover()} type="button">
                    {discoverBusy ? "Ищем…" : "Найти в T-Invest"}
                  </Button>
                ) : null}
                {discoverMessage ? (
                  <p className="muted tiny" data-testid="t-invest-discover-message">
                    {discoverMessage}
                  </p>
                ) : null}
                {candidates.length > 0 ? (
                  <ul className="mapping-candidates" data-testid="t-invest-candidates">
                    {candidates.map((candidate) => {
                      const meta = formatDiscoverCandidateMeta(candidate);
                      const trade = formatDiscoverCandidateTrade(candidate);
                      return (
                        <li className="mapping-candidate" key={candidate.provider_instrument_id}>
                          <div className="mapping-candidate__body">
                            <strong>
                              {candidate.name?.trim() ||
                                candidate.ticker?.trim() ||
                                candidate.provider_instrument_id}
                            </strong>
                            {meta ? <p className="muted tiny">{meta}</p> : null}
                            <p className="muted tiny">
                              {candidate.isin ? `${candidate.isin} · ` : ""}
                              {candidate.provider_instrument_id}
                              {candidate.position_uid
                                ? ` · position ${candidate.position_uid}`
                                : ""}
                            </p>
                            {trade ? <p className="muted tiny">{trade}</p> : null}
                          </div>
                          <Button
                            aria-label={`Выбрать ${candidate.provider_instrument_id}`}
                            disabled={formBusy}
                            onClick={() => chooseCandidate(candidate)}
                            type="button"
                          >
                            Выбрать
                          </Button>
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </>
            ) : (
              <>
                <p className="muted tiny" data-testid="moex-production-disabled-note">
                  Прямой MOEX ISS в production отключён. Сохранённое сопоставление можно править
                  вручную, но котировки по нему не запрашиваются, пока источник не сменят на
                  T-Invest.
                </p>
                <div className="form-row-2">
                  <Field htmlFor="mapping-provider" label="Провайдер">
                    <Input
                      id="mapping-provider"
                      onChange={(event) =>
                        setMoexDraft((current) => ({ ...current, provider: event.target.value }))
                      }
                      value={moexDraft.provider}
                    />
                  </Field>
                  <Field htmlFor="mapping-engine" label="Движок">
                    <Input
                      id="mapping-engine"
                      onChange={(event) =>
                        setMoexDraft((current) => ({ ...current, engine: event.target.value }))
                      }
                      value={moexDraft.engine}
                    />
                  </Field>
                </div>
                <div className="form-row-2">
                  <Field htmlFor="mapping-market" label="Рынок">
                    <Input
                      id="mapping-market"
                      onChange={(event) =>
                        setMoexDraft((current) => ({ ...current, market: event.target.value }))
                      }
                      value={moexDraft.market}
                    />
                  </Field>
                  <Field htmlFor="mapping-boardid" label="Режим торгов (boardid)">
                    <Input
                      id="mapping-boardid"
                      onChange={(event) =>
                        setMoexDraft((current) => ({ ...current, boardid: event.target.value }))
                      }
                      value={moexDraft.boardid}
                    />
                  </Field>
                </div>
                <Field htmlFor="mapping-secid" label="Код бумаги (secid)">
                  <Input
                    id="mapping-secid"
                    onChange={(event) =>
                      setMoexDraft((current) => ({ ...current, secid: event.target.value }))
                    }
                    value={moexDraft.secid}
                  />
                </Field>
              </>
            )}

            {localError || error ? (
              <div className="inline-alert inline-alert--error" role="alert">
                {localError ?? error}
              </div>
            ) : null}
            <div className="dialog__actions">
              <Button disabled={formBusy} onClick={onCancel} type="button">
                Закрыть
              </Button>
              {hasIdentity ? (
                <Button disabled={formBusy} onClick={() => void onClear()} type="button">
                  {busy ? "Сохраняем…" : "Удалить источник"}
                </Button>
              ) : null}
              {state === "excluded" ? (
                <Button disabled={formBusy} onClick={() => void onClearExclusion()} type="button">
                  {busy ? "Сохраняем…" : "Включить обновление"}
                </Button>
              ) : (
                <Button disabled={formBusy} onClick={() => void onExclude()} type="button">
                  {busy ? "Сохраняем…" : "Отключить обновление"}
                </Button>
              )}
              <Button disabled={formBusy} type="submit" variant="primary">
                {busy ? "Сохраняем…" : "Сохранить источник"}
              </Button>
            </div>
          </form>
        ) : (
          <div className="stack-8">
            <p>
              Этот тип инструмента обновляется вручную. Внешний источник здесь не обязателен и не
              заменяет ручную цену.
            </p>
            {error ? (
              <div className="inline-alert inline-alert--error" role="alert">
                {error}
              </div>
            ) : null}
            <div className="dialog__actions">
              <Button disabled={busy} onClick={onCancel} type="button">
                Закрыть
              </Button>
              {state === "excluded" ? (
                <Button disabled={busy} onClick={() => void onClearExclusion()} type="button">
                  {busy ? "Сохраняем…" : "Включить обновление"}
                </Button>
              ) : (
                <Button disabled={busy} onClick={() => void onExclude()} type="button">
                  {busy ? "Сохраняем…" : "Отключить обновление"}
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
