import { useEffect, useRef, useState } from "react";
import { formatApiError } from "../api/client";
import {
  confirmSourceReturnProof,
  getSourceReturnProofRequest,
  previewSourceReturnProof,
  type SourceReturnProof,
  type SourceReturnProofPreview,
} from "../api/sourceReturns";

type Props = {
  account: string;
  expected: { intake_id: number; manifest_digest: string }[];
  proof?: SourceReturnProof | null;
  loading: boolean;
  unavailable?: boolean;
  refresh: () => Promise<unknown>;
};

export function SourceReturnProofPanel({
  account,
  expected,
  proof,
  loading,
  unavailable = false,
  refresh,
}: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [preview, setPreview] = useState<SourceReturnProofPreview | null>(null);
  const [attested, setAttested] = useState(false);
  const [busy, setBusy] = useState(false);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  useEffect(
    () => () => {
      generation.current++;
      controller.current?.abort();
    },
    [],
  );
  function reset() {
    generation.current++;
    controller.current?.abort();
    setPreview(null);
    setAttested(false);
    setRequestId(null);
    setMessage("");
    setBusy(false);
  }
  async function check() {
    const own = ++generation.current;
    controller.current?.abort();
    controller.current = new AbortController();
    setPreview(null);
    setAttested(false);
    setMessage("");
    setBusy(true);
    try {
      const result = await previewSourceReturnProof(
        account,
        expected,
        files,
        controller.current.signal,
      );
      if (generation.current !== own) return;
      if (
        result.source_account !== account ||
        result.financial_authority !== "none" ||
        result.financial_effects !== 0
      ) {
        throw new Error("Ответ относится к другому источнику или изменяет финансовые данные");
      }
      setPreview(result);
    } catch (error) {
      if (generation.current === own) setMessage(formatApiError(error));
    } finally {
      if (generation.current === own) setBusy(false);
    }
  }
  async function save() {
    if (!preview || !attested || busy || requestId) return;
    const own = ++generation.current;
    controller.current = new AbortController();
    const id = crypto.randomUUID();
    setRequestId(id);
    setBusy(true);
    setMessage("");
    setPreview(null);
    setAttested(false); // Any ACK/GET failure must never re-enable POST.
    try {
      const ack = await confirmSourceReturnProof(account, preview, id, controller.current.signal);
      if (generation.current !== own) return;
      if (ack.request_id !== id || ack.source_account !== account)
        throw new Error("Подтверждение ответа не совпало");
      setMessage("Подтверждение сохранено. Перечитываем обычный расчёт без XML.");
      await refresh();
    } catch (error) {
      if (generation.current === own)
        setMessage(`Результат команды нужно проверить чтением: ${formatApiError(error)}`);
    } finally {
      if (generation.current === own) setBusy(false);
    }
  }
  async function recover() {
    if (!requestId || busy) return;
    const own = ++generation.current;
    setBusy(true);
    controller.current = new AbortController();
    try {
      const ack = await getSourceReturnProofRequest(requestId, controller.current.signal);
      if (generation.current !== own) return;
      if (ack.source_account !== account || ack.request_id !== requestId)
        throw new Error("Ответ относится к другому подтверждению");
      setMessage(
        ack.proof.status === "current"
          ? "Сохранение подтверждено чтением."
          : "Подтверждение устарело; требуется новая проверка оригиналов.",
      );
      await refresh();
    } catch (error) {
      if (generation.current === own) setMessage(formatApiError(error));
    } finally {
      if (generation.current === own) setBusy(false);
    }
  }
  return (
    <section aria-label="Подтверждение источников доходности">
      <h2>Подтверждение источников доходности</h2>
      <p>Счёт источника: {account}</p>
      {unavailable ? (
        <p role="status">
          Не удалось проверить актуальность источников. Подтверждение и сохранение недоступны до
          успешного чтения.
        </p>
      ) : loading ? (
        <p>Проверяем актуальность подтверждения…</p>
      ) : proof?.status === "current" ? (
        <p>
          Источник подтверждён: #{proof.proof_id} · {proof.version} · {proof.confirmed_at}. Обычный
          расчёт доступен без повторного выбора XML.
        </p>
      ) : proof?.status === "stale" ? (
        <p role="status">
          Подтверждение устарело: {proof.reason_codes.join(", ")}. До новой проверки действуют
          обычные причины NULL.
        </p>
      ) : (
        <p>
          Оригиналы можно проверить один раз и отдельно подтвердить сохранение доказательства
          источника.
        </p>
      )}
      <p>
        Сохраняется только доказательство источника. XML, рассчитанные суммы и проценты не
        сохраняются. Это не финансовое принятие. Месяцы с неизвестным погашением и аннулированием
        остаются недоступны.
      </p>
      <label>
        Оригиналы для подтверждения{" "}
        <input
          aria-label="Оригиналы для подтверждения"
          type="file"
          accept=".xml"
          multiple
          disabled={busy || loading || unavailable}
          onChange={(event) => {
            reset();
            setFiles(Array.from(event.target.files ?? []));
          }}
        />
      </label>
      <p>
        Выбрано файлов: {files.length}. Требуется полный набор: {expected.length}.
      </p>
      <button
        type="button"
        disabled={busy || loading || unavailable || files.length === 0 || !!requestId}
        onClick={() => void check()}
      >
        Проверить оригиналы
      </button>
      {preview && !loading && !unavailable && (
        <section aria-label="Preview подтверждения источника">
          <p>
            Проверено источников: {preview.source_count}. Месяцы custody-аннулирования:{" "}
            {preview.cancellation_months.join(", ")}; их блокировка сохраняется.
          </p>
          <p>
            Будет добавлено одно подтверждение источника. Другие записи и финансовые данные не
            меняются. При изменении зависимостей доказательство утратит силу.
          </p>
          <label>
            <input
              type="checkbox"
              checked={attested}
              onChange={(event) => setAttested(event.target.checked)}
            />
            Подтверждаю сохранение доказательства источника без финансового принятия
          </label>
          <button type="button" disabled={!attested || busy} onClick={() => void save()}>
            Сохранить подтверждение
          </button>
        </section>
      )}
      {message && <p role="status">{message}</p>}
      {unavailable && (
        <button type="button" disabled={busy} onClick={() => void refresh()}>
          Повторить чтение источников
        </button>
      )}
      {requestId && (
        <button type="button" disabled={busy} onClick={() => void recover()}>
          Проверить результат сохранения
        </button>
      )}
    </section>
  );
}
