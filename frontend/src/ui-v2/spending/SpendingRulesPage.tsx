import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { spendingApi, type SpendingCategory, type SpendingRule } from "../../api/spending";
import { Button, ConfirmDialog, Table, Td, Th } from "../../components/ui";
import sheet from "../ReportSheet.module.css";
import { UiV2Shell } from "../UiV2Shell";
import { UiV2Notice, UiV2Skeleton, UiV2WidgetState } from "../UiV2StateBlocks";
import { monthPath, Section, spendingPath, TypeSelect, validMonth } from "./common";
import styles from "./Spending.module.css";

type Action =
  | { kind: "merge"; from: SpendingCategory }
  | { kind: "rule"; rule: SpendingRule }
  | { kind: "link"; id: number; category: string };

function CategoryRow({
  category,
  aliases,
  disabled,
  onChange,
  onMerge,
}: {
  category: SpendingCategory;
  aliases: string[];
  disabled: boolean;
  onChange: (body: Partial<Pick<SpendingCategory, "name" | "expense_type">>) => Promise<boolean>;
  onMerge: () => void;
}) {
  const [name, setName] = useState<string | null>(null);
  const system = category.name === "Без категории";
  return (
    <tr id={`category-${category.id}`} className={styles.ruleTarget}>
      <Td>
        {name === null ? (
          category.name
        ) : (
          <form
            className={styles.ruleActions}
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim() && name.trim() !== category.name)
                void onChange({ name: name.trim() }).then((ok) => {
                  if (ok) setName(null);
                });
              else setName(null);
            }}
          >
            <input
              autoComplete="off"
              aria-label="Название категории"
              maxLength={128}
              value={name}
              disabled={disabled}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape" && !disabled) setName(null);
              }}
            />
            <Button type="submit" size="sm" disabled={disabled || !name.trim()}>
              Сохранить
            </Button>
          </form>
        )}
      </Td>
      <Td>
        <TypeSelect
          disabled={disabled}
          value={category.expense_type}
          label={`Тип: ${category.name}`}
          onChange={(expense_type) => void onChange({ expense_type })}
        />
      </Td>
      <Td>{aliases.length ? aliases.join(", ") : "—"}</Td>
      <Td numeric>—</Td>
      <Td>
        {!system && (
          <div className={styles.ruleActions}>
            <Button
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => setName(category.name)}
            >
              Переименовать
            </Button>
            <Button variant="ghost" size="sm" disabled={disabled} onClick={onMerge}>
              Объединить с…
            </Button>
          </div>
        )}
      </Td>
    </tr>
  );
}
export default function SpendingRulesPage() {
  const [params] = useSearchParams();
  const month = params.get("month");
  const { hash } = useLocation();
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [action, setAction] = useState<Action | null>(null);
  const [target, setTarget] = useState("");
  const categories = useQuery({
    queryKey: ["spending", "categories"],
    queryFn: ({ signal }) => spendingApi.categories(signal),
  });
  const rules = useQuery({
    queryKey: ["spending", "rules"],
    queryFn: ({ signal }) => spendingApi.rules(signal),
  });
  const links = useQuery({
    queryKey: ["spending", "links"],
    queryFn: ({ signal }) => spendingApi.links(signal),
  });
  const categoriesReady = Boolean(categories.data);
  useEffect(() => {
    if (categoriesReady && /^#category-\d+$/.test(hash))
      document.getElementById(hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [categoriesReady, hash]);

  async function write(command: () => Promise<void>) {
    if (busy) return false;
    setBusy(true);
    setFailed(false);
    try {
      await command();
      await cache.invalidateQueries({ queryKey: ["spending"] });
      return true;
    } catch {
      setFailed(true);
      await cache.invalidateQueries({ queryKey: ["spending"] });
      return false;
    } finally {
      setBusy(false);
    }
  }

  const merchantRules = rules.data?.filter((item) => item.scope === "merchant") ?? [];
  const manageableLinks = links.data?.filter((row) => row.id !== null && row.confirmed) ?? [];
  const targetCategory = categories.data?.find((item) => String(item.id) === target);
  const mergeTargets =
    action?.kind === "merge"
      ? (categories.data?.filter(
          (item) => item.id !== action.from.id && item.name !== "Без категории",
        ) ?? [])
      : [];
  const title =
    action?.kind === "merge"
      ? targetCategory
        ? `Объединить „${action.from.name}“ с „${targetCategory.name}“?`
        : "Объединить с…"
      : action?.kind === "rule"
        ? `Удалить правило для „${action.rule.key}“?`
        : action?.kind === "link"
          ? `Отменить связь для „${action.category}“?`
          : "";
  const description =
    action?.kind === "merge"
      ? targetCategory
        ? `Все операции „${action.from.name}“ за все месяцы перейдут в „${targetCategory.name}“. Категории банка „${action.from.name}“ будут относиться к „${targetCategory.name}“.`
        : "Выберите категорию."
      : action?.kind === "rule"
        ? "Уже загруженные операции не изменятся. При следующей загрузке такие операции снова попадут в „Нужно решить“."
        : "Запись месяца снова будет учитываться отдельно.";

  function confirm() {
    if (!action) return;
    void write(async () => {
      if (action.kind === "merge" && targetCategory) {
        const saved = await spendingApi.mergeCategory(action.from.id, targetCategory.id);
        const rows = await spendingApi.categories();
        if (
          rows.some((row) => row.id === action.from.id) ||
          !rows.some((row) => row.id === saved.id && row.id === targetCategory.id)
        )
          throw new Error();
      } else if (action.kind === "rule") {
        await spendingApi.deleteRule(action.rule.id);
        if ((await spendingApi.rules()).some((rule) => rule.id === action.rule.id))
          throw new Error();
      } else if (action.kind === "link") {
        await spendingApi.unlink(action.id);
        if ((await spendingApi.links()).some((link) => link.id === action.id)) throw new Error();
      }
    }).then((ok) => {
      if (ok) setAction(null);
    });
  }

  return (
    <UiV2Shell
      header={
        <div className={`${styles.actions} ${styles.screenHeader}`}>
          <h1>Категории трат</h1>
          <Link to={month && validMonth(month) ? monthPath(month) : spendingPath}>
            ← К расходам
          </Link>
        </div>
      }
    >
      <div className={sheet.sheet}>
        {failed && (
          <UiV2Notice title="Не удалось подтвердить сохранение" alert>
            Проверьте категории и правила.
          </UiV2Notice>
        )}
        {categories.isError && <UiV2WidgetState retry={() => void categories.refetch()} />}
        {rules.isError && <UiV2WidgetState retry={() => void rules.refetch()} />}
        {links.isError && <UiV2WidgetState retry={() => void links.refetch()} />}
        {(categories.isPending || rules.isPending || links.isPending) && (
          <UiV2Skeleton label="Загружаем категории и правила" />
        )}
        {categories.data && (
          <Section title="Категории">
            {categories.data.length === 0 ? (
              <UiV2WidgetState title="Категорий пока нет" />
            ) : (
              <Table>
                <thead>
                  <tr>
                    {["Категория", "Тип", "Категории банка", "Операций за 12 мес", ""].map(
                      (label) => (
                        <Th key={label}>{label}</Th>
                      ),
                    )}
                  </tr>
                </thead>
                <tbody>
                  {categories.data.map((category) => (
                    <CategoryRow
                      key={category.id}
                      category={category}
                      disabled={busy}
                      aliases={
                        rules.data
                          ?.filter(
                            (rule) =>
                              rule.scope === "bank_category" && rule.category_id === category.id,
                          )
                          .map((rule) => rule.key) ?? []
                      }
                      onMerge={() => {
                        setTarget("");
                        setAction({ kind: "merge", from: category });
                      }}
                      onChange={(body) =>
                        write(async () => {
                          const saved = await spendingApi.patchCategory(category.id, body);
                          const read = (await spendingApi.categories()).find(
                            (item) => item.id === category.id,
                          );
                          if (
                            !read ||
                            read.name !== saved.name ||
                            read.expense_type !== saved.expense_type
                          )
                            throw new Error();
                        })
                      }
                    />
                  ))}
                </tbody>
              </Table>
            )}
          </Section>
        )}
        {merchantRules.length > 0 && (
          <Section title="Правила по продавцу">
            <Table>
              <thead>
                <tr>
                  <Th>Продавец / получатель</Th>
                  <Th>Категория</Th>
                  <Th>Создано</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {merchantRules.map((rule) => (
                  <tr key={rule.id}>
                    <Td>{rule.key}</Td>
                    <Td>
                      {rule.action === "not_spending"
                        ? "Не трата"
                        : (categories.data?.find((item) => item.id === rule.category_id)?.name ??
                          "—")}
                    </Td>
                    <Td>—</Td>
                    <Td>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => setAction({ kind: "rule", rule })}
                      >
                        Удалить
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Section>
        )}
        {manageableLinks.length > 0 && (
          <Section title="Связи с записями месяца">
            <Table>
              <thead>
                <tr>
                  <Th>Запись месяца</Th>
                  <Th>Продавец</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {manageableLinks.map((link) => (
                  <tr key={link.id}>
                    <Td>{link.entry_category}</Td>
                    <Td>—</Td>
                    <Td>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => {
                          if (link.id !== null)
                            setAction({ kind: "link", id: link.id, category: link.entry_category });
                        }}
                      >
                        Отменить
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Section>
        )}
        {rules.data && links.data && merchantRules.length === 0 && manageableLinks.length === 0 && (
          <p className={sheet.muted}>
            Правил пока нет. Они появятся, когда вы примете решение при загрузке.
          </p>
        )}
        <ConfirmDialog
          open={action !== null}
          title={title}
          description={description}
          busy={busy}
          confirmLabel={
            action?.kind === "merge"
              ? "Объединить"
              : action?.kind === "rule"
                ? "Удалить"
                : "Отменить связь"
          }
          confirmDisabled={action?.kind === "merge" && !targetCategory}
          onConfirm={confirm}
          onCancel={() => setAction(null)}
        >
          {action?.kind === "merge" && (
            <label className={sheet.select}>
              Категория{" "}
              <select
                disabled={busy}
                value={target}
                onChange={(event) => setTarget(event.target.value)}
              >
                <option value="">Выберите категорию</option>
                {mergeTargets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </ConfirmDialog>
      </div>
    </UiV2Shell>
  );
}
