const BASE = "http://localhost:8000/api";

export function normalizeInput(raw: string): string {
  return raw.trim();
}

export interface Analysis {
  repo_id?: string;
  detected_server?: string | null;
  readme_flags?: Record<string, string>;
  gguf_files?: Array<{ path: string; size: number }>;
  weights_bytes?: number;
  downloaded?: Record<string, boolean>;
}

export interface DownloadedModel {
  server_id: string;
  repo_id: string;
  status: string;
}

export interface RunSummary {
  id: number;
  repo_id: string;
  requested_n: number;
  created_at: string;
  status: string;
}

export interface RunResult {
  id: number;
  run_id: number;
  server_id: string;
  flags: Record<string, string>;
  prompt_processing_tps: number | null;
  decode_tps: number | null;
  status: string;
  duration_s: number;
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
    request<Analysis>("/models/analyze", { method: "POST", body: JSON.stringify({ input }) }),
  generateConfigs: (body: unknown) =>
    request<{ configs: Array<{ flags: Record<string, string>; serving_command: string; bench_command: string[] }> }>("/configs/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  startBenchmark: (body: unknown) => request<{ run_id: number }>("/benchmarks", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  listModels: () => request<{ models: DownloadedModel[] }>("/models"),
  listRuns: () => request<{ runs: RunSummary[] }>("/benchmarks"),
  getRun: (runId: number) => request<{ results: RunResult[] }>(`/benchmarks/${runId}`),
  removeModel: (serverId: string, repoId: string) =>
    request<{ ok: boolean }>(`/models/${serverId}/${encodeURIComponent(repoId)}`, { method: "DELETE" }),
};
