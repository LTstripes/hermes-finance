/** Identity metadata only; linking never accepts source financial results. */
export type ReturnPeriod = { start: string; end: string };
export type ReturnAccountLink = {
  source_account_id: string;
  financial_account_id: number | null;
  account_type: "brokerage" | "iis" | null;
  label: string;
  status: "linked" | "unlinked";
  reason_codes: string[];
};
