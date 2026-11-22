import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ApiClientError } from "../../api/client";
import {
  spendingApi,
  type FileKind,
  type PreviewDecision,
  type Resolution,
  type SpendingException,
  type SpendingMonth,
  type SpendingPreview,
} from "../../api/spending";
import { Button } from "../../components/ui";
import { formatMonthKey, pluralRu } from "../../lib/format";
import { MonthNavigationGuard } from "../MonthNavigationGuard";
import sheet from "../ReportSheet.module.css";
import { UiV2Shell } from "../UiV2Shell";
import { UiV2Notice, UiV2Skeleton, UiV2WidgetState } from "../UiV2StateBlocks";
import { spendingMonthForm } from "../uiV2Copy";
import {
  currentMonth,
  importPath,
  monthPath,
  MonthSelect,
  Section,
  shiftMonth,
  TemplateButton,
  validMonth,
} from "./common";
import { needsDecision, type ResolvedException, SpendingExceptions } from "./SpendingExceptions";
import {
  FormatErrors,
  PreviewDetails,
  TotalChange,
  UnreadableRows,
} from "./SpendingPreviewDetails";
import { previewHeading } from "./previewCopy";
import styles from "./Spending.module.css";

type Files = Partial<Record<FileKind, File>>;
type Request = "preview" | "decide" | "apply";
type Failure = "preview" | "decide" | "stale" | "readback";
const excelWarning =
  "Это файл Excel. В Альфа-Банке выгрузите выписку в формате CSV и выберите её здесь.";
const backTitle = "Выйти без применения?";
const backCopy = "Решения на этой странице не сохранятся. Загруженные ранее траты не изменятся.";

function decisionBody(item: SpendingException, decision: Resolution): PreviewDecision | null {
  if (item.expense_entry_id && (decision.action === "link" || decision.action === "separate"))
    return {
      entry_links: [
        {
          expense_entry_id: item.expense_entry_id,
          action: decision.action,
          operation_ids: decision.operation_ids,
          remember: decision.remember,
        },
      ],
    };
  if (
    !item.fingerprint ||
    item.ordinal === undefined ||
    ["link", "unlink", "acknowledge"].includes(decision.action)
  )
    return null;
  const { id: _id, action, operation_ids: _operations, ...fields } = decision;
  if (action === "link" || action === "unlink" || action === "acknowledge") return null;
  return { choices: [{ ...fields, action, fingerprint: item.fingerprint, ordinal: item.ordinal }] };
}

function readbackMatches(applied: SpendingMonth, saved: SpendingMonth) {
  // Both responses use the diary read model. Check its full saved projection,
  // including source coverage, operation identities and open exceptions.
  return saved.loaded && JSON.stringify(applied) === JSON.stringify(saved);
}

function UploadFiles({
  month,
  files,
  changeFiles,
  changeMonth,
  busy,
  onCheck,
}: {
  month: string;
  files: Files;
  changeFiles: (kind: FileKind, file?: File) => void;
  changeMonth: (month: string) => void;
  busy: Request | null;
  onCheck: () => void;
}) {
  const [invalidFiles, setInvalidFiles] = useState<Partial<Record<FileKind, string>>>({});
  const today = new Date();
  const now = currentMonth(today);
  return (
    <fieldset className={styles.fileForm} disabled={busy !== null}>
      <div className={styles.formGrid}>
        <MonthSelect month={month} onChange={changeMonth} />
        {(month === now || (month === shiftMonth(now, -1) && today.getDate() <= 5)) && (
          <p className={sheet.muted}>
            Банк ещё проводит покупки за этот месяц. Лучше загрузить выписку после 5-го числа, иначе
            часть операций будет „в обработке“.
          </p>
        )}
        {(
          [
            ["statement", ".csv", "Выписка Альфа-Банка (CSV)"],
            ["manual", ".md", "Ручной файл (.md)"],
          ] as const
        ).map(([kind, accept, title]) => (
          <div className={styles.fileField} key={kind}>
            <strong>{title}</strong>
            <div className={styles.actions}>
              <label className="btn btn--secondary">
                Выбрать файл
                <input
                  aria-label={title}
                  accept={accept}
                  type="file"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (!file) return;
                    if (/\.xlsx?$/i.test(file.name)) {
                      setInvalidFiles({ ...invalidFiles, [kind]: excelWarning });
                      changeFiles(kind, undefined);
                    } else {
                      setInvalidFiles({ ...invalidFiles, [kind]: undefined });
                      changeFiles(kind, file);
                    }
                  }}
                />
              </label>
              <span className={sheet.muted}>{files[kind]?.name ?? "не выбран"}</span>
              {files[kind] && (
                <Button
                  variant="ghost"
                  aria-label={`Очистить: ${title}`}
                  onClick={() => changeFiles(kind, undefined)}
                >
                  ✕
                </Button>
              )}
              {invalidFiles[kind] && (
                <span role="alert" className={styles.negative}>
                  {invalidFiles[kind]}
                </span>
              )}
            </div>
          </div>
        ))}
        <div className={styles.actions}>
          <TemplateButton month={month} />
        </div>
        <div className={styles.actions}>
          <Button
            variant="primary"
            disabled={busy !== null || (!files.statement && !files.manual)}
            onClick={onCheck}
          >
            {busy === "preview" ? "Проверяем…" : "Проверить"}
          </Button>
        </div>
      </div>
    </fieldset>
  );
}

function SavedReview({ month }: { month: string }) {
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [resolved, setResolved] = useState<ResolvedException[]>([]);
  const exceptions = useQuery({
    queryKey: ["spending", "exceptions", month],
    queryFn: ({ signal }) => spendingApi.exceptions(month, signal),
  });
  const categories = useQuery({
    queryKey: ["spending", "categories"],
    queryFn: ({ signal }) => spendingApi.categories(signal),
  });
  async function resolve(item: SpendingException, decision: Resolution) {
    setBusy(true);
    setFailed(false);
    try {
      const result = await spendingApi.resolve(month, decision);
      const confirmed = await spendingApi.exceptions(month);
      if (JSON.stringify(result.exceptions) !== JSON.stringify(confirmed)) throw new Error();
      cache.setQueryData(["spending", "exceptions", month], confirmed);
      await cache.invalidateQueries({ queryKey: ["spending"] });
      setResolved((previous) => [...previous, { item, decision }]);
    } catch {
      setFailed(true);
      await exceptions.refetch();
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className={styles.actions}>
        <span>{formatMonthKey(month)}</span>
        <Button disabled={busy} onClick={() => navigate(importPath(month))}>
          Загрузить заново
        </Button>
      </div>
      {failed && (
        <UiV2Notice title="Не удалось подтвердить сохранение" alert>
          Проверьте траты {spendingMonthForm(month, "genitive")}.
        </UiV2Notice>
      )}
      {exceptions.isError || categories.isError ? (
        <UiV2WidgetState
          retry={() => void Promise.all([exceptions.refetch(), categories.refetch()])}
        />
      ) : !exceptions.data || !categories.data ? (
        <UiV2Skeleton label="Загружаем исключения" />
      ) : (
        <Section title="Нужно решить">
          <SpendingExceptions
            month={month}
            items={exceptions.data.items}
            resolved={resolved}
            categories={categories.data}
            disabled={busy}
            saved
            onResolve={(item, decision) => void resolve(item, decision)}
          />
          {exceptions.data.items.length === 0 && (
            <UiV2WidgetState title="Открытых исключений нет" />
          )}
        </Section>
      )}
    </>
  );
}

function Upload({ month, changeMonth }: { month: string; changeMonth: (next: string) => void }) {
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [files, setFiles] = useState<Files>({});
  const [preview, setPreview] = useState<SpendingPreview | null>(null);
  const [resolved, setResolved] = useState<ResolvedException[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const [busy, setBusy] = useState<Request | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [leaving, setLeaving] = useState(false);
  const request = useRef<Request | null>(null);
  const categories = useQuery({
    queryKey: ["spending", "categories"],
    queryFn: ({ signal }) => spendingApi.categories(signal),
    enabled: Boolean(preview),
  });

  function changeFiles(kind: FileKind, file?: File) {
    setFiles((current) => ({ ...current, [kind]: file }));
    setPreview(null);
    setResolved([]);
    setFailure(null);
    setConfirmed(false);
    setSkipped(false);
  }
  function begin(next: Request) {
    if (request.current) return false;
    request.current = next;
    setBusy(next);
    setFailure(null);
    return true;
  }
  function end() {
    request.current = null;
    setBusy(null);
  }
  async function check(replay = false) {
    if (!begin("preview")) return;
    setConfirmed(false);
    try {
      let next = await spendingApi.preview(month, files);
      const carried: ResolvedException[] = [];
      if (replay) {
        if (skipped) {
          const lines = next.file_errors.flatMap((error) =>
            error.file === "manual" && error.line !== undefined ? [error.line] : [],
          );
          if (lines.length)
            next = await spendingApi.decide(next.preview_id, { skip_error_lines: lines });
        }
        for (const old of resolved) {
          const item = next.exceptions.find(
            (entry) =>
              entry.id === old.item.id ||
              (old.item.fingerprint &&
                entry.fingerprint === old.item.fingerprint &&
                entry.ordinal === old.item.ordinal),
          );
          if (!item) continue;
          const body = decisionBody(item, old.decision);
          if (!body) continue;
          if (
            old.decision.duplicate_of_id != null &&
            !item.candidates.some((candidate) => candidate.id === old.decision.duplicate_of_id)
          )
            continue;
          if (
            old.decision.operation_ids?.some(
              (id) => !item.candidates.some((candidate) => candidate.id === id),
            )
          )
            continue;
          next = await spendingApi.decide(next.preview_id, body);
          carried.push({ item, decision: old.decision });
        }
      } else {
        setSkipped(false);
      }
      setResolved(carried);
      setPreview(next);
    } catch {
      setFailure("preview");
    } finally {
      end();
    }
  }
  async function decide(body: PreviewDecision, entry?: ResolvedException) {
    if (!preview || !begin("decide")) return false;
    try {
      setPreview(await spendingApi.decide(preview.preview_id, body));
      setConfirmed(false);
      if (entry)
        setResolved((previous) => [
          ...previous.filter(({ item }) => item.id !== entry.item.id),
          entry,
        ]);
      return true;
    } catch (error) {
      setFailure(
        error instanceof ApiClientError && [404, 409].includes(error.status) ? "stale" : "decide",
      );
      return false;
    } finally {
      end();
    }
  }
  async function apply() {
    if (!preview || !begin("apply")) return;
    let saved: SpendingMonth;
    let counts: { added: number; changed: number; removed: number };
    try {
      const { month: applied, ...changes } = await spendingApi.apply(
        preview.preview_id,
        confirmed,
        skipped,
      );
      saved = await spendingApi.month(month);
      if (!readbackMatches(applied, saved)) throw new Error();
      counts = changes;
    } catch (error) {
      setFailure(
        error instanceof ApiClientError && [404, 409].includes(error.status) ? "stale" : "readback",
      );
      end();
      return;
    }
    cache.setQueryData(["spending", "month", month], saved);
    void cache.invalidateQueries({ queryKey: ["spending"], refetchType: "none" });
    setLeaving(true);
    navigate(monthPath(month), { replace: true, state: { spending: { month, ...counts } } });
  }
  const manualRows =
    preview?.file_errors.filter((error) => error.file === "manual" && error.line !== undefined) ??
    [];
  const missingManual = Boolean(
    files.manual && preview && !preview.sets.some((set) => set.kind === "manual"),
  );
  const missingStatement = Boolean(
    files.statement && preview && !preview.sets.some((set) => set.kind === "statement"),
  );
  const stale = preview?.stale || failure === "stale";
  const blocked =
    busy !== null ||
    stale ||
    failure === "readback" ||
    !preview?.applicable ||
    (preview.blocking.needs_removal_confirmation && !confirmed);
  const hasPreview = Boolean(preview);
  const exceptions =
    preview?.exceptions.map((item) => {
      if (item.group !== "new_category") return item;
      const row = preview.operations?.find(
        (operation) =>
          operation.fingerprint === item.fingerprint && operation.ordinal === item.ordinal,
      );
      return row?.category ? { ...item, category: row.category } : item;
    }) ?? [];
  const deferred = exceptions.filter(needsDecision).length;
  return (
    <>
      {!leaving && (
        <MonthNavigationGuard
          dirty={hasPreview && failure !== "readback"}
          pending={busy === "apply"}
          discardTitle={backTitle}
          discardDescription={backCopy}
          discardLabel="Выйти"
        />
      )}
      <UploadFiles
        {...{ month, files, busy }}
        changeFiles={changeFiles}
        changeMonth={changeMonth}
        onCheck={() => void check()}
      />
      {failure === "preview" && (
        <UiV2Notice title="Проверка не выполнена" retry={() => void check(hasPreview)}>
          Файлы не загружены, данные не изменились. Попробуйте ещё раз.
        </UiV2Notice>
      )}
      {failure === "decide" && (
        <UiV2Notice title="Не удалось принять решение" alert>
          Попробуйте ещё раз.
        </UiV2Notice>
      )}
      {stale && (
        <>
          <UiV2Notice
            title={`Расходы ${spendingMonthForm(month, "genitive")} изменились, пока вы разбирали файл`}
            alert
          >
            Проверьте файлы ещё раз.
          </UiV2Notice>
          <Button disabled={busy !== null} onClick={() => void check(true)}>
            Проверить заново
          </Button>
        </>
      )}
      {failure === "readback" && (
        <UiV2Notice title="Не удалось подтвердить сохранение" alert>
          Проверьте траты {spendingMonthForm(month, "genitive")}. Если данных нет, загрузите файлы
          ещё раз — повторная загрузка ничего не задвоит.
        </UiV2Notice>
      )}
      {preview && (
        <>
          <FormatErrors preview={preview} />
          {preview.sets.length > 0 && (
            <div
              className={busy === "decide" ? styles.faded : undefined}
              aria-busy={busy === "decide"}
            >
              <Section title={previewHeading(month)}>
                <PreviewDetails
                  preview={preview}
                  confirmed={confirmed}
                  setConfirmed={setConfirmed}
                  disabled={busy !== null || Boolean(stale)}
                  onSeparate={(expense_entry_id) =>
                    void decide({ entry_links: [{ expense_entry_id, action: "separate" }] })
                  }
                />
              </Section>
            </div>
          )}
          {((exceptions.length > 0 && preview.sets.length > 0) ||
            resolved.length > 0 ||
            manualRows.length > 0) && (
            <Section title="Нужно решить">
              {categories.isError && <UiV2WidgetState retry={() => void categories.refetch()} />}
              <SpendingExceptions
                items={
                  preview.sets.length > 0
                    ? exceptions.filter(
                        (item) => !resolved.some((entry) => entry.item.id === item.id),
                      )
                    : []
                }
                resolved={resolved}
                categories={categories.data ?? []}
                month={month}
                disabled={busy !== null || Boolean(stale) || !categories.data}
                onResolve={(item, decision) => {
                  const body = decisionBody(item, decision);
                  if (body) void decide(body, { item, decision });
                }}
                extra={
                  manualRows.length ? (
                    <UnreadableRows
                      rows={manualRows}
                      skipped={skipped}
                      disabled={busy !== null || Boolean(stale)}
                      onSkip={(next) => {
                        void decide({
                          skip_error_lines: next
                            ? manualRows.flatMap((row) =>
                                row.line === undefined ? [] : [row.line],
                              )
                            : [],
                        }).then((ok) => {
                          if (ok) setSkipped(next);
                        });
                      }}
                    />
                  ) : undefined
                }
              />
            </Section>
          )}
          {(preview.sets.length > 0 || manualRows.length > 0) && (
            <div className={styles.saveBar}>
              <div className={styles.actions}>
                <span>
                  <TotalChange preview={preview} />
                </span>
                <div className={styles.actions}>
                  <Link className="btn btn--secondary" to={monthPath(month)}>
                    Отмена
                  </Link>
                  <Button variant="primary" disabled={blocked} onClick={() => void apply()}>
                    {busy === "apply" ? "Применяем…" : "Применить"}
                  </Button>
                </div>
              </div>
              {preview.blocking.needs_removal_confirmation && !confirmed && (
                <p className={sheet.muted}>Подтвердите, что операции будут удалены.</p>
              )}
              {!preview.applicable && manualRows.length > 0 && (
                <p className={sheet.muted}>Подтвердите пропуск нечитаемых строк.</p>
              )}
              {preview.applicable && missingManual && (
                <p className={sheet.muted}>Будет применена только выписка</p>
              )}
              {preview.applicable && missingStatement && (
                <p className={sheet.muted}>Будет применён только ручной файл</p>
              )}
              {deferred > 0 && (
                <p className={sheet.muted}>
                  {deferred}{" "}
                  {pluralRu(deferred, ["решение отложено", "решения отложены", "решений отложено"])}{" "}
                  — их можно принять позже на экране „Расходы“.
                </p>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}

export default function SpendingImportPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("month");
  const month = requested ?? shiftMonth(currentMonth(), -1);
  const valid = validMonth(month) && params.getAll("month").length <= 1;
  const review = params.get("review") === "1";
  return (
    <UiV2Shell
      showRefresh={false}
      header={
        <div className={`${styles.actions} ${styles.screenHeader}`}>
          <h1>Загрузка расходов</h1>
          <Link to={valid ? monthPath(month) : "/v2/spending"}>← К расходам</Link>
        </div>
      }
    >
      <div className={sheet.sheet}>
        {!valid ? (
          <>
            <UiV2WidgetState title="Такого месяца нет" />
            <Link to={importPath(shiftMonth(currentMonth(), -1))}>К последнему месяцу</Link>
          </>
        ) : review ? (
          <SavedReview key={month} month={month} />
        ) : (
          <Upload key={month} month={month} changeMonth={(next) => setParams({ month: next })} />
        )}
      </div>
    </UiV2Shell>
  );
}
