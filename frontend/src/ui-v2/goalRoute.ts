export function uiV2GoalsPath(monthId: number | null): string {
  return monthId === null ? "/v2/income/goals" : `/v2/income/goals?month=${monthId}`;
}
