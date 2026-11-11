import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { instrumentBackTarget } from "./returns/cardPresentation";
import { validIsin } from "./returns/navigation";
import { ReturnsInstrumentCard } from "./returns/ReturnsInstrumentCard";
import { UiV2Shell } from "./UiV2Shell";

/** One ISIN read: no all-instrument overview or hidden account/month request. */
export default function UiV2ReturnsInstrumentPage({
  accountLabels = {},
}: {
  accountLabels?: Record<string, string>;
}) {
  const { isin } = useParams<{ isin: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const back = instrumentBackTarget(params.get("back"));
  const selection = (key: string) =>
    params.getAll(key).length > 1 ? "invalid-duplicate" : params.get(key);
  return (
    <UiV2Shell active="returns" header={null} showRefresh={false}>
      {validIsin(isin) ? (
        <ReturnsInstrumentCard
          key={isin}
          isin={isin}
          revision={0}
          standalone
          initialName={
            typeof location.state?.instrumentName === "string"
              ? location.state.instrumentName
              : undefined
          }
          accountLabels={accountLabels}
          capitalAccount={
            params.getAll("capital_account").length === 1 ? params.get("capital_account") : null
          }
          capitalRequested={params.has("capital_account")}
          selectedScope={selection("detail_scope")}
          selectedStart={selection("detail_start")}
          selectedEnd={selection("detail_end")}
          backLabel={back.startsWith("/v2/capital") ? "К капиталу" : "К доходности"}
          close={() => navigate(back)}
        />
      ) : (
        <p role="alert">
          Инструмент не выбран.{" "}
          <button type="button" onClick={() => navigate(back)}>
            Назад
          </button>
        </p>
      )}
    </UiV2Shell>
  );
}
