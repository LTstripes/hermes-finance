import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listAllSourceIntakes } from "../api/sourceIntake";
import { getSourceInstrumentReturns, getSourceMonthlyReturns } from "../api/sourceReturns";
import { SourceIntakeUpload } from "../components/month-close/SourceIntakeUpload";
import { SourceReturnProofPanel } from "./SourceReturnProofPanel";
import { UiV2BondSlice } from "./UiV2BondSlice";
import { UiV2Loading, UiV2Notice, isQueryReady } from "./UiV2StateBlocks";

/** Existing source evidence tools, mounted only after opening the account's details. */
export default function ReturnsSourceDiagnostics({ account }: { account: string }) {
  const client = useQueryClient();
  const intakes = useQuery({
    queryKey: ["source-intakes", "all"],
    queryFn: ({ signal }) => listAllSourceIntakes(signal),
  });
  const monthly = useQuery({
    queryKey: ["source-returns", "monthly", account],
    queryFn: ({ signal }) => getSourceMonthlyReturns(account, signal),
  });
  const instruments = useQuery({
    queryKey: ["source-returns", "instruments", account],
    queryFn: ({ signal }) => getSourceInstrumentReturns(account, signal),
  });
  const expected = (intakes.data ?? [])
    .filter(
      (item) =>
        item.document.filename_account === account ||
        item.document.source_accounts?.includes(account) ||
        // Saved parser DTOs need not contain the optional aggregate. Match
        // only explicit row identities; never infer a native account suffix.
        [
          ...(item.document.positions ?? []),
          ...(item.document.rub_money ?? []),
          ...(item.document.money ?? []),
          ...(item.document.trades ?? []).map((row) => row.core),
        ].some((row) => row.source_account === account),
    )
    .map((item) => ({ intake_id: item.id, manifest_digest: item.manifest_digest }));
  const unavailable =
    intakes.isError ||
    monthly.isError ||
    (isQueryReady(monthly) && monthly.data?.source_account !== account);
  const proof = unavailable ? undefined : monthly.data?.source_proof;
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["source-returns"] }),
      client.invalidateQueries({ queryKey: ["source-intakes", "all"] }),
      client.invalidateQueries({ queryKey: ["returns"] }),
    ]);
  return (
    <>
      <SourceIntakeUpload
        onSaved={() => void client.invalidateQueries({ queryKey: ["returns"] })}
      />
      <SourceReturnProofPanel
        key={JSON.stringify([
          account,
          expected,
          proof?.proof_id,
          proof?.status,
          proof?.currentness,
          unavailable,
        ])}
        account={account}
        expected={expected}
        proof={proof}
        loading={
          intakes.isFetching ||
          monthly.isFetching ||
          !isQueryReady(intakes) ||
          !isQueryReady(monthly)
        }
        unavailable={unavailable}
        refresh={refresh}
      />
      {instruments.isError ||
      (isQueryReady(instruments) && instruments.data?.source_account !== account) ? (
        <UiV2Notice
          title="Не удалось прочитать инструменты"
          retry={() => void instruments.refetch()}
        >
          Повтори чтение данных выбранного счёта.
        </UiV2Notice>
      ) : isQueryReady(instruments) && instruments.data?.source_account === account ? (
        <UiV2BondSlice account={account} sources={instruments.data} />
      ) : (
        <UiV2Loading label="Читаем инструменты выбранного счёта…" />
      )}
    </>
  );
}
