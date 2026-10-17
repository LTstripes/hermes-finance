import { useQuery } from "@tanstack/react-query";
import { listAccounts } from "../api/accounts";
import { InstrumentCashIncome } from "./InstrumentCashIncome";

/** Isolated UAT entry: reuse the native selector/readers without the writable App. */
export function InstrumentUatPage() {
  const accounts = useQuery({
    queryKey: ["uat-accounts"],
    queryFn: ({ signal }) => listAccounts(signal),
  });
  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: 24 }}>
      <h1>Проверка наблюдений по бумаге</h1>
      <p>Изолированный режим только для чтения. Снимок не обновляется из рабочего приложения.</p>
      {accounts.isPending ? <p role="status">Читаем список счетов…</p> : null}
      {accounts.isError ? (
        <p role="alert">Не удалось прочитать счета. Перезагрузите страницу.</p>
      ) : null}
      {accounts.isSuccess && !accounts.isFetching ? (
        <InstrumentCashIncome accounts={accounts.data} start="" end="" accountId={null} />
      ) : null}
    </main>
  );
}
