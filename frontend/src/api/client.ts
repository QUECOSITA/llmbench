const BASE = "http://localhost:8000/api";

export function normalizeInput(raw: string): string {
  return raw.trim();
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getServers: () => request<{ readiness: Record<string, boolean>; hardware: Record<string, unknown> }>("/servers"),
  analyze: (input: string) =>
    request<Record<string, unknown>>("/models/analyze", { method: "POST", body: JSON.stringify({ input }) }),
  generateConfigs: (body: unknown) =>
    request<{ configs: Array<{ flags: Record<string, string>; serving_command: string; bench_command: string[] }> }>("/configs/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  startBenchmark: (body: unknown) => request<{ run_id: number }>("/benchmarks", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  listModels: () => request<{ models: unknown[] }>("/models"),
  listRuns: () => request<{ runs: unknown[] }>("/benchmarks"),
  getRun: (runId: number) => request<{ results: unknown[] }>(`/benchmarks/${runId}`),
  removeModel: (serverId: string, repoId: string) =>
    request<{ ok: boolean }>(`/models/${serverId}/${encodeURIComponent(repoId)}`, { method: "DELETE" }),
};
