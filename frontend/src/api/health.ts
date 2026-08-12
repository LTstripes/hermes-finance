export type HealthResponse = {
  status: "ok";
  version: string;
};

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch("/api/health", { signal });
  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }

  const health = (await response.json()) as HealthResponse;
  if (health.status !== "ok" || typeof health.version !== "string") {
    throw new Error("Backend returned an invalid health status");
  }
  return health;
}
