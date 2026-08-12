import { createServer } from "node:http";

const models = new Map<string, { server_id: string; repo_id: string; status: string; gguf_filename: string | null }>();
function seedModel(server_id: string, repo_id: string, gguf_filename: string | null = null) {
  models.set(`${server_id}::${repo_id}`, { server_id, repo_id, status: "downloaded", gguf_filename });
}
seedModel("llama.cpp", "org/model", "model.gguf");

const runs = [{ id: 1, repo_id: "org/model", requested_n: 1, created_at: "", status: "completed" }];

const server = createServer(async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") {
    res.statusCode = 204;
    res.end();
    return;
  }
  const body: Record<string, unknown> = {};
  if (req.method === "DELETE" && req.url?.startsWith("/api/models/")) {
    const repoId = decodeURIComponent(req.url.replace("/api/models/", ""));
    for (const [k, v] of [...models]) {
      if (v.repo_id === repoId) models.delete(k);
    }
    Object.assign(body, { ok: true });
  } else if (req.url?.startsWith("/api/servers")) {
    Object.assign(body, { readiness: { "llama.cpp": true, "speed-bench": true }, hardware: { gpu_vram_gb: 24 } });
  } else if (req.url?.startsWith("/api/speed-bench/info")) {
    Object.assign(body, {
      benches: ["qualitative", "throughput_1k", "throughput_2k", "throughput_8k", "throughput_16k", "throughput_32k"],
      categories: {
        qualitative: ["coding", "humanities", "math", "qa", "rag", "reasoning", "stem", "writing", "multilingual", "summarization", "roleplay"],
        throughput_1k: ["high_entropy", "mixed", "low_entropy"],
        throughput_2k: ["high_entropy", "mixed", "low_entropy"],
        throughput_8k: ["high_entropy", "mixed", "low_entropy"],
        throughput_16k: ["high_entropy", "mixed", "low_entropy"],
        throughput_32k: ["high_entropy", "mixed", "low_entropy"],
      },
    });
  } else if (req.url?.startsWith("/api/models/analyze")) {
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk);
    let repoId = "org/model";
    try {
      const parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (parsed.input) repoId = String(parsed.input).split("/resolve/")[0];
    } catch {}
    const hasCommand = repoId !== "org/noserve";
    Object.assign(body, {
      repo_id: repoId,
      detected_server: "llama.cpp",
      readme_has_serving_command: hasCommand,
      readme_flags: { "--ctx-size": "8192" },
      weights_bytes: 4e9,
      gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
      fit_verdict: { stage: "gpu", warning: false, needed_gb: 3.8 },
      model_arch: { layers: 32, heads: 32, hidden: 4096, max_ctx: 8192 },
      hardware: { gpu_vram_gb: 24, ram_total_gb: 64, gpu_name: "RTX 4090" },
      downloaded: { "llama.cpp": repoId === "org/model" },
    });
  } else if (req.url?.startsWith("/api/models/download/cancel")) {
    Object.assign(body, { ok: true });
  } else if (req.url?.startsWith("/api/models/download/prune-answer")) {
    Object.assign(body, { ok: true });
  } else if (req.url?.startsWith("/api/models/download")) {
    Object.assign(body, { ok: true });
  } else if (req.url?.startsWith("/api/configs/generate")) {
    Object.assign(body, {
      configs: [{
        flags: { "--ctx-size": "8192" },
        serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
        bench_tool: "llama-bench",
        fit: { stage: "gpu", label: "FITS VRAM", fits_vram: true, offloaded: false, needed_gb: 3.8, kv_gb: 4.3, weights_gb: 4 },
      }],
    });
  } else if (req.method === "GET" && req.url === "/api/benchmarks") {
    Object.assign(body, { runs });
  } else if (req.method === "POST" && req.url?.startsWith("/api/benchmarks")) {
    Object.assign(body, { run_id: 1 });
  } else if (req.method === "DELETE" && req.url?.startsWith("/api/benchmarks")) {
    runs.length = 0;
    Object.assign(body, { ok: true });
  } else if (req.url?.startsWith("/api/benchmarks/")) {
    Object.assign(body, {
      status: "completed",
      total: 1,
      results: [{
        config_id: 1,
        server_id: "llama.cpp",
        flag_conf: { "--ctx-size": "8192" },
        serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
        prompt_processing_tps: 100.0,
        decode_tps: 42.0,
      }],
    });
  } else if (req.url?.startsWith("/api/models")) {
    Object.assign(body, { models: [...models.values()] });
  }
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(body));
});

server.listen(8000);
