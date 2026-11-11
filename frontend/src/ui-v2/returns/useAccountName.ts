import { useQuery } from "@tanstack/react-query";
import { listAccounts } from "../../api/accounts";
import { queryKeys } from "../../queryClient";
import type { AccountLink } from "./model";

/** Catalogue names are labels only; source identity and financial scope stay intact. */
export function useAccountName(links: readonly (AccountLink | null | undefined)[]) {
  const query = useQuery({
    queryKey: queryKeys.accounts,
    queryFn: ({ signal }) => listAccounts(signal),
    enabled: links.some((link) => link?.status === "linked" && link.financial_account_id != null),
  });
  return (link: AccountLink | null | undefined, fallback: string) => {
    if (!link) return fallback;
    const account =
      link.status === "linked" && !query.isError && Array.isArray(query.data)
        ? query.data.find((account) => account.id === link.financial_account_id)
        : undefined;
    return (
      account?.name ??
      (link.account_type === "iis"
        ? "ИИС"
        : link.account_type === "brokerage"
          ? "Брокерский"
          : "Счёт")
    );
  };
}
