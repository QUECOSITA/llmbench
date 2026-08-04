import { createServer } from "node:http";

const server = createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") {
    res.statusCode = 204;
    res.end();
    return;
  }
  const body: Record<string, unknown> = {};
  if (req.url?.startsWith("/api/servers")) {
    Object.assign(body, { readiness: { "llama.cpp": true, vllm: true, sglang: true }, hardware: { gpu_vram_gb: 24 } });
  } else if (req.url?.startsWith("/api/models/analyze")) {
    Object.assign(body, {
      repo_id: "org/model", detected_server: "vllm",
      readme_flags: { "--max-model-len": "8192" }, weights_bytes: 4e9,
      fit_verdict: { stage: "gpu", warning: false, needed_gb: 3.8 },
      model_arch: { layers: 32, heads: 32, hidden: 4096, max_ctx: 8192 },
      hardware: { gpu_vram_gb: 24, ram_total_gb: 64, gpu_name: "RTX 4090" },
      downloaded: { "llama.cpp": false, vllm: false, sglang: false },
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
        flags: { "--max-model-len": "8192" },
        serving_command: "vllm serve org/model --max-model-len 8192",
        fit: { stage: "gpu", label: "FITS VRAM", fits_vram: true, offloaded: false, needed_gb: 3.8, kv_gb: 4.3, weights_gb: 4 },
      }],
    });
  } else if (req.url?.startsWith("/api/benchmarks")) {
    Object.assign(body, { run_id: 1 });
  } else if (req.url?.startsWith("/api/models")) {
    Object.assign(body, { models: [] });
  }
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(body));
});

server.listen(8000);
