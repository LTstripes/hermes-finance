import { apiRequest } from "./client";
import type { ClassReturns } from "./types";

export type ClassCoverage = ClassReturns["coverage_provenance"][number];
export type ClassCoverageWrite = Omit<ClassCoverage, "id" | "revision">;

export function listClassCoverages(signal?: AbortSignal) {
  return apiRequest<ClassCoverage[]>("/api/class-evidence/coverages", { signal });
}

export function saveClassCoverage(body: ClassCoverageWrite, row?: ClassCoverage) {
  return apiRequest<ClassCoverage>(`/api/class-evidence/coverages${row ? `/${row.id}` : ""}`, {
    method: row ? "PUT" : "POST",
    body,
    ...(row ? { headers: { "If-Match": String(row.revision) } } : {}),
  });
}
