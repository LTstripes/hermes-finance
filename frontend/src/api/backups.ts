import { apiRequest } from "./client";
import type { BackupMetadata, RestoreResponse } from "./types";

export function listBackups(signal?: AbortSignal): Promise<BackupMetadata[]> {
  return apiRequest<BackupMetadata[]>("/api/backups", { method: "GET", signal });
}

export function createBackup(signal?: AbortSignal): Promise<BackupMetadata> {
  return apiRequest<BackupMetadata>("/api/backups", { method: "POST", signal });
}

export function restoreBackup(backupId: string): Promise<RestoreResponse> {
  return apiRequest<RestoreResponse>(`/api/backups/${encodeURIComponent(backupId)}/restore`, {
    method: "POST",
    body: { confirm: true },
  });
}
