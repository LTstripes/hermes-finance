import { useEffect, useId, useState, type FormEvent } from "react";

import type { Instrument, InstrumentMarketMapping, MarketIdentityWrite } from "../api/types";
import {
  defaultMappingDraft,
  formatMarketIdentity,
  MAPPING_STATE_LABELS,
  MAPPING_SUPPORTED_TYPES,
  mappingStateTone,
} from "../lib/marketData";
import { labelOf } from "../lib/labels";
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
};

function draftFromMapping(
  instrument: Instrument,
  mapping: InstrumentMarketMapping | null,
): MarketIdentityWrite {
  if (mapping?.identity) {
    return { ...mapping.identity };
  }
  return defaultMappingDraft(instrument.instrument_type);
}

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
}: Props) {
  const titleId = useId();
  const descriptionId = useId();
  const [draft, setDraft] = useState<MarketIdentityWrite>(defaultMappingDraft("stock"));
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !instrument) return;
    setDraft(draftFromMapping(instrument, mapping));
    setLocalError(null);
  }, [open, instrument, mapping]);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) onCancel();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, busy, onCancel]);

  if (!open || !instrument) return null;

  const supported = MAPPING_SUPPORTED_TYPES.has(instrument.instrument_type);
  const state = mapping?.state ?? "unmapped";
  const hasIdentity = mapping?.identity != null;

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    const payload: MarketIdentityWrite = {
      provider: draft.provider.trim(),
      engine: draft.engine.trim(),
      market: draft.market.trim(),
      boardid: draft.boardid.trim(),
      secid: draft.secid.trim(),
    };
    if (
      !payload.provider ||
      !payload.engine ||
      !payload.market ||
      !payload.boardid ||
      !payload.secid
    ) {
      setLocalError("Заполни провайдер, движок, рынок, режим торгов и код бумаги.");
      return;
    }
    setLocalError(null);
    await onSave(payload);
  }

  function updateField(field: keyof MarketIdentityWrite, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <div
        aria-describedby={descriptionId}
        aria-labelledby={titleId}
        aria-modal="true"
        className="dialog dialog--wide"
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
              <Field htmlFor="mapping-provider" label="Провайдер">
                <Input
                  id="mapping-provider"
                  onChange={(event) => updateField("provider", event.target.value)}
                  value={draft.provider}
                />
              </Field>
              <Field htmlFor="mapping-engine" label="Движок">
                <Input
                  id="mapping-engine"
                  onChange={(event) => updateField("engine", event.target.value)}
                  value={draft.engine}
                />
              </Field>
            </div>
            <div className="form-row-2">
              <Field htmlFor="mapping-market" label="Рынок">
                <Input
                  id="mapping-market"
                  onChange={(event) => updateField("market", event.target.value)}
                  value={draft.market}
                />
              </Field>
              <Field htmlFor="mapping-boardid" label="Режим торгов (boardid)">
                <Input
                  id="mapping-boardid"
                  onChange={(event) => updateField("boardid", event.target.value)}
                  value={draft.boardid}
                />
              </Field>
            </div>
            <Field htmlFor="mapping-secid" label="Код бумаги (secid)">
              <Input
                id="mapping-secid"
                onChange={(event) => updateField("secid", event.target.value)}
                value={draft.secid}
              />
            </Field>
            {localError || error ? (
              <div className="inline-alert inline-alert--error" role="alert">
                {localError ?? error}
              </div>
            ) : null}
            <div className="dialog__actions">
              <Button disabled={busy} onClick={onCancel} type="button">
                Закрыть
              </Button>
              {hasIdentity ? (
                <Button disabled={busy} onClick={() => void onClear()} type="button">
                  {busy ? "Сохраняем…" : "Удалить источник"}
                </Button>
              ) : null}
              {state === "excluded" ? (
                <Button disabled={busy} onClick={() => void onClearExclusion()} type="button">
                  {busy ? "Сохраняем…" : "Включить обновление"}
                </Button>
              ) : (
                <Button disabled={busy} onClick={() => void onExclude()} type="button">
                  {busy ? "Сохраняем…" : "Отключить обновление"}
                </Button>
              )}
              <Button disabled={busy} type="submit" variant="primary">
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
