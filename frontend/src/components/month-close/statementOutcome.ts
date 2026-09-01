export type AlfaStatementTransientOutcome =
  | { kind: "applied"; selectedCount: number }
  | { kind: "zero_rows" };

export function parseAlfaStatementTransientOutcome(
  value: unknown,
): AlfaStatementTransientOutcome | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as { kind?: unknown; selectedCount?: unknown };
  if (candidate.kind === "zero_rows") return { kind: "zero_rows" };
  if (
    candidate.kind === "applied" &&
    typeof candidate.selectedCount === "number" &&
    Number.isInteger(candidate.selectedCount) &&
    candidate.selectedCount > 0
  ) {
    return { kind: "applied", selectedCount: candidate.selectedCount };
  }
  return null;
}
