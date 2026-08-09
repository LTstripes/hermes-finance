import { apiRequest } from "./client";
import type { BackupMetadata } from "./types";

export function listBackups(signal?: AbortSignal): Promise<BackupMetadata[]> {
  return apiRequest<BackupMetadata[]>("/api/backups", { method: "GET", signal });
}

export function createBackup(signal?: AbortSignal): Promise<BackupMetadata> {
  return apiRequest<BackupMetadata>("/api/backups", { method: "POST", signal });
}
