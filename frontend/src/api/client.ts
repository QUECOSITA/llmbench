const BASE = "http://localhost:8000/api";

export interface ApiErrorContext {
  active_run?: { id?: number | null; repo_id?: string | null; requested_n?: number | null; created_at?: string | null; status?: string | null } | null;
  active_run_id?: number | null;
  config_index?: number;
  server_id?: string | null;
  bench_tool?: string | null;
  [key: string]: unknown;
}

export class ApiError extends Error {
  status: number;
  detail: string;
  context: ApiErrorContext;

  constructor(status: number, detail: string, context: ApiErrorContext = {}) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.context = context;
  }
}

export function normalizeInput(raw: string): string {
  return raw.trim();
}

export interface FitVerdict {
  stage: string;
  warning: boolean;
  needed_gb: number;
}

export interface GgufFile {
  path: string;
  size: number;
  fit?: FitVerdict;
}

export interface ModelArch {
  layers: number;
  heads: number;
  hidden: number;
  max_ctx: number;
}

export interface ConfigFit {
  stage: "gpu" | "offload" | "cpu" | "no_fit";
  label: string;
  fits_vram: boolean;
  offloaded: boolean;
  needed_gb: number;
  kv_gb: number;
  weights_gb: number;
}

export interface SpeedBenchInfo {
  benches: string[];
  categories: Record<string, string[]>;
}

export interface Analysis {
  repo_id?: string;
  detected_server?: string | null;
  readme_has_serving_command?: boolean;
  auto_bench_tool?: string;
  readme_flags?: Record<string, string>;
  readme_flags_by_server?: Record<string, Record<string, string>>;
  gguf_files?: GgufFile[];
  downloaded_ggufs?: Record<string, string[]>;
  weights_bytes?: number;
  downloaded?: Record<string, boolean>;
  fit_verdict?: FitVerdict;
  model_arch?: ModelArch;
  hardware?: { gpu_vram_gb?: number; ram_total_gb?: number; gpu_name?: string };
}

export interface DownloadedModel {
  server_id: string;
  repo_id: string;
  status: string;
  gguf_filename?: string | null;
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

export interface RunDetail {
  status?: string;
  total?: number;
  results: Array<{
    config_id: number;
    server_id: string;
    flag_conf: Record<string, string>;
    serving_command?: string;
    prompt_processing_tps: number | null;
    decode_tps: number | null;
    duration_s?: number | null;
    result_status?: string;
  }>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    let context: ApiErrorContext = {};
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      if (body?.context && typeof body.context === "object") context = body.context;
    } catch {
      const text = await res.text();
      if (text) detail = text.slice(0, 300);
    }
    throw new ApiError(res.status, detail, context);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getServers: () => request<{ readiness: Record<string, boolean>; hardware: Record<string, unknown> }>("/servers"),
  getSpeedBenchInfo: () => request<SpeedBenchInfo>("/speed-bench/info"),
  analyze: (input: string) =>
    request<Analysis>("/models/analyze", { method: "POST", body: JSON.stringify({ input }) }),
  generateConfigs: (body: {
    repo_id: string;
    server_id: string;
    n: number;
    vram_gb: number;
    readme_flags: Record<string, string>;
    weights_bytes?: number;
    ram_gb?: number;
    model_arch?: ModelArch;
    bench_tool?: string;
  }) =>
    request<{
      configs: Array<{
        flags: Record<string, string>;
        serving_command: string;
        bench_command: string[];
        bench_tool?: string;
        bench_flags?: string;
        fit: ConfigFit | null;
      }>;
    }>("/configs/generate", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  startBenchmark: (body: unknown) => request<{ run_id: number }>("/benchmarks", {
    method: "POST",
    body: JSON.stringify(body),
  }),
  cancelBenchmark: () => request<{ ok: boolean }>("/benchmarks/cancel", { method: "POST" }),
  listModels: () => request<{ models: DownloadedModel[] }>("/models"),
  downloadModel: (body: { repo_id: string; server_id: string; gguf_filename?: string; gguf_filenames?: string[] }) =>
    request<{ ok: boolean }>("/models/download", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  cancelDownload: () => request<{ ok: boolean }>("/models/download/cancel", { method: "POST" }),
  answerPrune: (answer: "y" | "n") =>
    request<{ ok: boolean }>("/models/download/prune-answer", {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
  listRuns: () => request<{ runs: RunSummary[] }>("/benchmarks"),
  clearRuns: () => request<{ ok: boolean }>("/benchmarks", { method: "DELETE" }),
  getRun: (runId: number) => request<RunDetail>(`/benchmarks/${runId}`),
  removeModel: (repoId: string) =>
    request<{ ok: boolean }>(`/models/${encodeURIComponent(repoId)}`, { method: "DELETE" }),
};
