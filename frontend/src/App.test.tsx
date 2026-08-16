import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";

vi.mock("./api/client", () => ({
  api: {
    getServers: vi.fn().mockResolvedValue({ readiness: {}, hardware: {} }),
    getSpeedBenchInfo: vi.fn().mockResolvedValue({
      benches: ["qualitative", "throughput_1k", "throughput_2k", "throughput_8k", "throughput_16k", "throughput_32k"],
      categories: {
        qualitative: ["coding", "humanities", "math", "qa", "rag", "reasoning", "stem", "writing", "multilingual", "summarization", "roleplay"],
        throughput_1k: ["high_entropy", "mixed", "low_entropy"],
        throughput_2k: ["high_entropy", "mixed", "low_entropy"],
        throughput_8k: ["high_entropy", "mixed", "low_entropy"],
        throughput_16k: ["high_entropy", "mixed", "low_entropy"],
        throughput_32k: ["high_entropy", "mixed", "low_entropy"],
      },
    }),
    listModels: vi.fn().mockResolvedValue({ models: [] }),
    listRuns: vi.fn().mockResolvedValue({ runs: [] }),
    analyze: vi.fn().mockResolvedValue({ repo_id: "org/model", detected_server: "llama.cpp", readme_flags: {}, downloaded: { "llama.cpp": true } }),
    generateConfigs: vi.fn().mockResolvedValue({
      configs: [{ flags: { "--n-gpu": "1" }, serving_command: "python serve.py", bench_command: [] }],
    }),
    startBenchmark: vi.fn().mockResolvedValue({ run_id: 1 }),
    cancelBenchmark: vi.fn().mockResolvedValue({ ok: true }),
    getRun: vi.fn().mockResolvedValue({ status: "running", total: 1, results: [] }),
    downloadModel: vi.fn().mockResolvedValue({ ok: true }),
    cancelDownload: vi.fn().mockResolvedValue({ ok: true }),
    answerPrune: vi.fn().mockResolvedValue({ ok: true }),
    removeModel: vi.fn(),
  },
}));

vi.mock("./ws/useBenchmarkProgress", async (importOriginal) => {
  const mod = await importOriginal<typeof import("./ws/useBenchmarkProgress")>();
  return { ...mod, useBenchmarkProgress: vi.fn().mockReturnValue([]) };
});

vi.mock("./ws/useDownloadProgress", () => ({
  useDownloadProgress: vi.fn().mockReturnValue([]),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

test("LOAD on a downloaded row fills MODEL INPUT and analyzes", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listModels).mockResolvedValue({
    models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValue({ repo_id: "org/model", detected_server: "llama.cpp", readme_flags: {}, downloaded: { "llama.cpp": true } });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await screen.findByText("llama.cpp");
  fireEvent.click(screen.getByRole("button", { name: "LOAD" }));

  await waitFor(() => expect(analyzeSpy).toHaveBeenCalledWith("org/model"));
  const input = screen.getByPlaceholderText(/model/i) as HTMLInputElement;
  expect(input.value).toBe("org/model");
});

test("LOAD on a downloaded gguf row fills MODEL INPUT and analyzes the file-qualified ref", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listModels).mockResolvedValue({
    models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded", gguf_filename: "model.gguf" }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValue({ repo_id: "org/model", detected_server: "llama.cpp", readme_flags: {}, downloaded: { "llama.cpp": true } });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await screen.findByText("org/model/model.gguf");
  fireEvent.click(screen.getByRole("button", { name: "LOAD" }));

  await waitFor(() => expect(analyzeSpy).toHaveBeenCalledWith("org/model/model.gguf"));
  const input = screen.getByPlaceholderText(/model/i) as HTMLInputElement;
  expect(input.value).toBe("org/model/model.gguf");
});

test("REMOVE deletes the whole repo and refreshes the list", async () => {
  const { api } = await import("./api/client");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(api.listModels)
    .mockResolvedValueOnce({
      models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" }],
    })
    .mockResolvedValueOnce({ models: [] });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await screen.findByText("org/model");
  fireEvent.click(screen.getByRole("button", { name: "REMOVE" }));

  await waitFor(() => expect(api.removeModel).toHaveBeenCalledWith("org/model"));
  expect(await screen.findByText("no models downloaded")).toBeInTheDocument();
});

test("REMOVE on a gguf row deletes only that file and refreshes the list", async () => {
  const { api } = await import("./api/client");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.mocked(api.listModels)
    .mockResolvedValueOnce({
      models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded", gguf_filename: "model.Q4_K_M.gguf" }],
    })
    .mockResolvedValueOnce({ models: [] });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await screen.findByText("org/model/model.Q4_K_M.gguf");
  fireEvent.click(screen.getByRole("button", { name: "REMOVE" }));

  await waitFor(() => expect(api.removeModel).toHaveBeenCalledWith("org/model/model.Q4_K_M.gguf"));
  expect(await screen.findByText("no models downloaded")).toBeInTheDocument();
});

test("renders the instrument header with panel structure", async () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const header = await screen.findByText(/LLM\s*BENCH/i);
  expect(header).toBeInTheDocument();
  expect(document.querySelector(".instrument")).not.toBeNull();
});

test("onRun rejection resets running state and shows error", async () => {
  const { api } = await import("./api/client");
  const startBenchmarkSpy = vi.spyOn(api, "startBenchmark");
  startBenchmarkSpy.mockRejectedValueOnce(new Error("409: already running"));

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  // Analyze a model
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  const analyzeBtn = screen.getByText(/analyze/i);
  fireEvent.click(analyzeBtn);

  // Wait for analysis
  await screen.findByText(/org\/model/i);

  // Generate configs
  const generateBtn = screen.getByText(/generate/i);
  fireEvent.click(generateBtn);
  await screen.findByText(/python serve/i);

  // Run (will fail)
  const runBtn = screen.getByText(/run benchmark/i);
  fireEvent.click(runBtn);

  // After rejection, button should be re-enabled (not disabled)
  await waitFor(() => {
    const btn = screen.getByText(/run benchmark/i);
    expect(btn).not.toBeDisabled();
  });
});

test("successful run shows initial progress label", async () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/python serve/i);
  fireEvent.click(screen.getByText(/run benchmark/i));
  await screen.findByText(/config 1\/1/i);
});

test("run that fails on the backend re-enables RUN and shows the failure", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.getRun).mockResolvedValue({ status: "failed", total: 1, results: [] });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/python serve/i);
  fireEvent.click(screen.getByText(/run benchmark/i));

  await waitFor(() => {
    expect(screen.getByText(/run benchmark/i)).not.toBeDisabled();
  }, { timeout: 3000 });
  expect(await screen.findByText(/run failed/i)).toBeInTheDocument();
});

test("RUN toggles to CANCEL and cancelling aborts the run without an error", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.getRun).mockResolvedValue({ status: "aborted", total: 1, results: [] });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/python serve/i);
  fireEvent.click(screen.getByText(/run benchmark/i));

  await waitFor(() => {
    expect(screen.getByText(/cancel benchmark/i)).toBeEnabled();
  });
  fireEvent.click(screen.getByText(/cancel benchmark/i));
  expect(vi.mocked(api.cancelBenchmark)).toHaveBeenCalled();

  await waitFor(() => {
    expect(screen.getByText(/run benchmark/i)).toBeEnabled();
  }, { timeout: 3000 });
  expect(screen.queryByText(/run failed/i)).not.toBeInTheDocument();
});

test("completed run populates ranked results and re-enables RUN", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.getRun).mockResolvedValue({
    status: "completed",
    total: 1,
    results: [
      {
        config_id: 1,
        server_id: "llama.cpp",
        flag_conf: { "--max-model-len": "8192" },
        serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
        prompt_processing_tps: 100.0,
        decode_tps: 42.0,
      },
    ],
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/python serve/i);
  fireEvent.click(screen.getByText(/run benchmark/i));

  await waitFor(() => {
    const table = document.querySelector(".results-table") as HTMLElement | null;
    expect(table).not.toBeNull();
    expect(within(table!).getByText("42.0")).toBeInTheDocument();
  }, { timeout: 3000 });
  await waitFor(() => {
    expect(screen.getByText(/run benchmark/i)).not.toBeDisabled();
  }, { timeout: 3000 });
});

test("409 already-running switches into watch mode showing the live run", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.startBenchmark).mockRejectedValueOnce({
    status: 409,
    detail: "A benchmark is already running",
    context: { active_run: { id: 7, repo_id: "org/other", requested_n: 3, status: "running" } },
  });
  vi.mocked(api.getRun).mockResolvedValue({
    status: "running",
    total: 3,
    results: [
      {
        config_id: 1,
        server_id: "llama.cpp",
        flag_conf: { "--max-model-len": "8192" },
        serving_command: "llama-server --hf-repo org/other --hf-file model.gguf --ctx-size 8192",
        prompt_processing_tps: 100.0,
        decode_tps: 42.0,
      },
    ],
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/python serve/i);
  fireEvent.click(screen.getByText(/run benchmark/i));

  await waitFor(() => {
    expect(screen.getByText(/watching benchmark run #7 in progress/i)).toBeInTheDocument();
  });
  await waitFor(() => {
    expect(screen.getByText(/cancel benchmark/i)).toBeEnabled();
  });
  await waitFor(() => {
    const table = document.querySelector(".results-table") as HTMLElement | null;
    expect(within(table!).getByText("42.0")).toBeInTheDocument();
  }, { timeout: 3000 });
  expect(vi.mocked(api.getRun)).toHaveBeenCalledWith(7);
});

test("fit line renders NO FIT when verdict is no_fit", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    fit_verdict: { stage: "no_fit", warning: true, needed_gb: 40.5 },
    hardware: { gpu_vram_gb: 8, ram_total_gb: 32, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": false },
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));

  expect(await screen.findByText(/NO FIT/i)).toBeInTheDocument();
  expect(screen.getByText(/40\.5 GB/)).toBeInTheDocument();
});

test("fit line renders FITS VRAM when verdict is gpu", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    fit_verdict: { stage: "gpu", warning: false, needed_gb: 3.8 },
    hardware: { gpu_vram_gb: 24, ram_total_gb: 64, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": false },
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/FITS VRAM/i);

  expect(screen.getByText(/FITS VRAM/i)).toBeInTheDocument();
  expect(screen.getByText(/3\.8 GB/)).toBeInTheDocument();
  expect(screen.queryByText(/NO FIT/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/OFFLOADS TO RAM/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/headroom tight/i)).not.toBeInTheDocument();
});

test("fit line renders OFFLOADS TO RAM when verdict is ram_offload", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    fit_verdict: { stage: "ram_offload", warning: false, needed_gb: 14.2 },
    hardware: { gpu_vram_gb: 8, ram_total_gb: 64, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": false },
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));

  expect(await screen.findByText(/OFFLOADS TO RAM/i)).toBeInTheDocument();
  expect(screen.getByText(/14\.2 GB/)).toBeInTheDocument();
});

test("download flow: click Download, shows downloading then downloaded and refreshes list", async () => {
  const { api } = await import("./api/client");
  const { useDownloadProgress } = await import("./ws/useDownloadProgress");
  vi.mocked(api.analyze).mockResolvedValueOnce({ repo_id: "org/model", detected_server: "llama.cpp", readme_flags: {}, downloaded: { "llama.cpp": false } });
  vi.mocked(api.listModels).mockClear();
  const downloadModelSpy = vi.spyOn(api, "downloadModel");
  downloadModelSpy.mockClear();
  downloadModelSpy.mockResolvedValueOnce({ ok: true });

  const view = render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  const downloadBtn = within(screen.getByText("llama.cpp:").closest("span")!).getByText("Download");
  fireEvent.click(downloadBtn);
  expect(await screen.findByText(/downloading/i)).toBeInTheDocument();
  expect(downloadModelSpy).toHaveBeenCalledWith({ repo_id: "org/model", server_id: "llama.cpp" });

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_log", server_id: "llama.cpp", repo_id: "org/model", line: "Fetching..." },
    { type: "download_done", server_id: "llama.cpp", repo_id: "org/model", status: "downloaded", local_path: "/x" },
  ]);
  view.rerender(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  expect(await screen.findByText("downloaded")).toBeInTheDocument();
  await waitFor(() => expect(api.listModels).toHaveBeenCalledTimes(2));
});

test("download for direct file link passes the single gguf filename in gguf_filenames", async () => {
  const { api } = await import("./api/client");
  const downloadModelSpy = vi.spyOn(api, "downloadModel");
  downloadModelSpy.mockResolvedValueOnce({ ok: true });

  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    gguf_files: [{ path: "model.Q4_K_M.gguf", size: 4_000_000_000 }],
    downloaded: { "llama.cpp": false },
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "https://huggingface.co/org/model/resolve/main/model.Q4_K_M.gguf" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  const downloadBtn = within(screen.getByText("llama.cpp:").closest("span")!).getByText("Download");
  fireEvent.click(downloadBtn);

  expect(await screen.findByText(/downloading/i)).toBeInTheDocument();
  expect(downloadModelSpy).toHaveBeenCalledWith({
    repo_id: "org/model",
    server_id: "llama.cpp",
    gguf_filenames: ["model.Q4_K_M.gguf"],
  });
});

test("cancel flow: CANCEL shows prune prompt, answering y completes", async () => {
  const { api } = await import("./api/client");
  const { useDownloadProgress } = await import("./ws/useDownloadProgress");
  vi.mocked(api.analyze).mockResolvedValueOnce({ repo_id: "org/model", detected_server: "llama.cpp", readme_flags: {}, downloaded: { "llama.cpp": false } });
  const cancelSpy = vi.spyOn(api, "cancelDownload").mockResolvedValue({ ok: true });
  const pruneSpy = vi.spyOn(api, "answerPrune").mockResolvedValue({ ok: true });
  vi.mocked(useDownloadProgress).mockReturnValue([]);

  const view = render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  fireEvent.click(within(screen.getByText("llama.cpp:").closest("span")!).getByText("Download"));
  expect(await screen.findByRole("button", { name: /cancel/i })).toBeInTheDocument();

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_started", server_id: "llama.cpp", repo_id: "org/model", command: "hf download org/model" },
    { type: "download_log", server_id: "llama.cpp", repo_id: "org/model", line: "Fetching..." },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(cancelSpy).toHaveBeenCalled();

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_cancelled", server_id: "llama.cpp", repo_id: "org/model" },
    { type: "prune_started", server_id: "llama.cpp", repo_id: "org/model", command: "hf cache prune --format human" },
    { type: "prune_log", server_id: "llama.cpp", repo_id: "org/model", line: "About to delete 1 incomplete download(s)." },
    { type: "prune_prompt", server_id: "llama.cpp", repo_id: "org/model" },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  const yBtn = screen.getByRole("button", { name: "y" });
  fireEvent.click(yBtn);
  expect(pruneSpy).toHaveBeenCalledWith("y");

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "prune_done", server_id: "llama.cpp", repo_id: "org/model", accepted: true },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  expect(await screen.findByText(/cache pruned/i)).toBeInTheDocument();
  const span = within(screen.getByText("llama.cpp:").closest("span")!);
  expect(span.getByRole("button", { name: /^download$/i })).toBeInTheDocument();
});

test("edited config serving_command is sent to the benchmark", async () => {
  const { api } = await import("./api/client");
  const startSpy = vi.spyOn(api, "startBenchmark").mockResolvedValue({ run_id: 1 });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/python serve/i);

  const textarea = screen.getByDisplayValue("python serve.py");
  fireEvent.change(textarea, { target: { value: "python serve.py --ctx-size 54000" } });

  fireEvent.click(screen.getByText(/run benchmark/i));
  await waitFor(() => expect(startSpy).toHaveBeenCalled());
  const body = startSpy.mock.calls[0][0] as { configs: Array<{ serving_command: string }> };
  expect(body.configs[0].serving_command).toBe("python serve.py --ctx-size 54000");
});

test("run payload round-trips bench_tool", async () => {
  const { api } = await import("./api/client");
  const startSpy = vi.spyOn(api, "startBenchmark").mockResolvedValue({ run_id: 1 });
  vi.mocked(api.generateConfigs).mockResolvedValue({
    configs: [
      { flags: {}, serving_command: "llama-server --spec-type draft-mtp", bench_command: [], bench_tool: "speed-bench", fit: null },
    ],
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/llama-server --spec-type/i);
  fireEvent.click(screen.getByText(/run benchmark/i));
  await waitFor(() => expect(startSpy).toHaveBeenCalled());
  const body = startSpy.mock.calls[0][0] as { configs: Array<{ bench_tool?: string }> };
  expect(body.configs[0].bench_tool).toBe("speed-bench");
});

test("shows the bench tool selector only when README proposes no serving config and passes bench_tool to generate", async () => {
  const { api } = await import("./api/client");
  const generateSpy = vi.spyOn(api, "generateConfigs").mockResolvedValue({
    configs: [{ flags: {}, serving_command: "llama-server --hf-repo org/model --hf-file model.gguf", bench_command: [], bench_tool: "llama-bench", fit: null }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    auto_bench_tool: "llama-bench",
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  const select = screen.getByLabelText(/bench tool/i) as HTMLSelectElement;
  expect(select.value).toBe("llama-bench");

  fireEvent.change(select, { target: { value: "speed-bench" } });
  fireEvent.click(screen.getByText(/generate/i));
  await waitFor(() => expect(generateSpy).toHaveBeenCalled());
  const body = generateSpy.mock.calls[0][0] as { bench_tool?: string };
  expect(body.bench_tool).toBe("speed-bench");
});

test("defaults the selector to auto_bench_tool=speed-bench from analyze", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/Qwen3-MTP",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    auto_bench_tool: "speed-bench",
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/Qwen3-MTP" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/Qwen3-MTP/i);

  const select = screen.getByLabelText(/bench tool/i) as HTMLSelectElement;
  expect(select.value).toBe("speed-bench");
});

test("no bench tool selector and no bench_tool in generate payload when README proposes a serving config", async () => {
  const { api } = await import("./api/client");
  const generateSpy = vi.spyOn(api, "generateConfigs").mockResolvedValue({
    configs: [{ flags: {}, serving_command: "llama-server --hf-repo org/model --hf-file model.gguf", bench_command: [], bench_tool: "llama-bench", fit: null }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: true,
    readme_flags: {},
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  expect(screen.queryByLabelText(/bench tool/i)).not.toBeInTheDocument();
  fireEvent.click(screen.getByText(/generate/i));
  await waitFor(() => expect(generateSpy).toHaveBeenCalled());
  const body = generateSpy.mock.calls[0][0] as { bench_tool?: string };
  expect(body.bench_tool).toBeUndefined();
});

test("run payload round-trips edited bench_flags", async () => {
  const { api } = await import("./api/client");
  const startSpy = vi.spyOn(api, "startBenchmark").mockResolvedValue({ run_id: 1 });
  vi.mocked(api.generateConfigs).mockResolvedValue({
    configs: [
      { flags: {}, serving_command: "llama-server --spec-type draft-mtp", bench_command: [], bench_tool: "speed-bench", bench_flags: "--bench qualitative --category all --limit 1 --osl 528", fit: null },
    ],
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/llama-server --spec-type/i);

  const textarea = screen.getByDisplayValue("--bench qualitative --category all --limit 1 --osl 528");
  fireEvent.change(textarea, { target: { value: "--bench qualitative --category coding" } });

  fireEvent.click(screen.getByText(/run benchmark/i));
  await waitFor(() => expect(startSpy).toHaveBeenCalled());
  const body = startSpy.mock.calls[0][0] as { configs: Array<{ bench_flags?: string }> };
  expect(body.configs[0].bench_flags).toBe("--bench qualitative --category coding");
});

test("detection returning null hides the select, shows the unsupported notice, and disables GENERATE/RUN", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: null,
    readme_flags: {},
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  expect(screen.queryByLabelText(/serving server/i)).not.toBeInTheDocument();
  expect(
    await screen.findByText(/model not supported by llama.cpp/i),
  ).toBeInTheDocument();
  expect(screen.getByText("GENERATE")).toBeDisabled();
  expect(screen.getByText("RUN BENCHMARK")).toBeDisabled();
});

test("GENERATE with no detected server and no manual pick stays disabled", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.generateConfigs).mockClear();
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: null,
    readme_flags: {},
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  fireEvent.click(screen.getByText("GENERATE"));
  expect(screen.getByText("GENERATE")).toBeDisabled();
  expect(vi.mocked(api.generateConfigs)).not.toHaveBeenCalled();
});

test("only the README-detected server appears in the select and download row", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listModels).mockResolvedValue({ models: [] });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    downloaded: { "llama.cpp": false },
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  const select = screen.getByLabelText(/serving server/i) as HTMLSelectElement;
  expect(select.value).toBe("llama.cpp");
  expect(select.querySelectorAll("option").length).toBe(1);
  expect(screen.getByText("llama.cpp:")).toBeInTheDocument();
  expect(screen.getByText("GENERATE")).toBeDisabled();
  expect(screen.getByText("RUN BENCHMARK")).toBeDisabled();
});

test("no serving command in README shows warning and hides Download until YES", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    downloaded: { "llama.cpp": false },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/may not be loadable by LLMBENCH/i);

  expect(screen.getByText(/YES — DOWNLOAD ANYWAY/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
});

test("confirming unsupported download reveals the Download button", async () => {
  const { api } = await import("./api/client");
  const downloadModelSpy = vi.spyOn(api, "downloadModel").mockResolvedValue({ ok: true });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    downloaded: { "llama.cpp": false },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/may not be loadable by LLMBENCH/i);

  fireEvent.click(screen.getByText(/YES — DOWNLOAD ANYWAY/i));
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  expect(downloadModelSpy).toHaveBeenCalledWith({
    repo_id: "org/model",
    server_id: "llama.cpp",
    gguf_filenames: ["model.gguf"],
  });
});

test("declining unsupported download keeps Download hidden", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    downloaded: { "llama.cpp": false },
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/may not be loadable by LLMBENCH/i);

  fireEvent.click(screen.getByRole("button", { name: "NO" }));
  expect(screen.queryByRole("button", { name: /YES — DOWNLOAD ANYWAY/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "NO" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
  expect(api.downloadModel).not.toHaveBeenCalled();
});

test("GENERATE stays disabled until the model is downloaded, then enables after download", async () => {
  const { api } = await import("./api/client");
  const { useDownloadProgress } = await import("./ws/useDownloadProgress");
  vi.mocked(api.listModels).mockResolvedValue({ models: [] });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    downloaded: { "llama.cpp": false },
  });

  const view = render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  expect(screen.getByText("GENERATE")).toBeDisabled();

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_done", server_id: "llama.cpp", repo_id: "org/model", status: "downloaded", local_path: "/x" },
  ]);
  view.rerender(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await waitFor(() => expect(screen.getByText("GENERATE")).not.toBeDisabled());
});

test("GENERATE is enabled when the model is already downloaded at analyze time", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    downloaded: { "llama.cpp": true },
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  expect(screen.getByText("GENERATE")).not.toBeDisabled();
});

test("LOAD of a downloaded model with no serving command warns without a download prompt", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listModels).mockResolvedValue({
    models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValue({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: false,
    gguf_files: [{ path: "model.gguf", size: 4_000_000_000 }],
    readme_flags: {},
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  await screen.findByText("llama.cpp");
  fireEvent.click(screen.getByRole("button", { name: "LOAD" }));
  await screen.findByText(/may not be loadable by LLMBENCH/i);

  expect(screen.queryByText(/YES — DOWNLOAD ANYWAY/i)).not.toBeInTheDocument();
  expect(screen.getByText("downloaded")).toBeInTheDocument();
});

test("LOAD of a model that does not fit shows the NO FIT warning", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listModels).mockResolvedValue({
    models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValue({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_has_serving_command: true,
    readme_flags: {},
    fit_verdict: { stage: "no_fit", warning: true, needed_gb: 40.5 },
    hardware: { gpu_vram_gb: 8, ram_total_gb: 32, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  await screen.findByText("llama.cpp");
  fireEvent.click(screen.getByRole("button", { name: "LOAD" }));
  await screen.findByText(/doesn't fit this machine/i);
});

test("getSpeedBenchInfo returns benches and categories", async () => {
  const { api } = await import("./api/client");
  const info = await api.getSpeedBenchInfo();
  expect(info.benches).toContain("qualitative");
  expect(info.categories.qualitative).toContain("coding");
});

test("CLEAR empties the ranked results table", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.getRun).mockResolvedValue({
    status: "completed",
    total: 1,
    results: [
      {
        config_id: 1,
        server_id: "llama.cpp",
        flag_conf: { "--max-model-len": "8192" },
        serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
        prompt_processing_tps: 100.0,
        decode_tps: 42.0,
      },
    ],
  });
  vi.mocked(api.generateConfigs).mockResolvedValue({
    configs: [{ flags: { "--n-gpu": "1" }, serving_command: "python serve.py", bench_command: [], fit: null }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValue({ repo_id: "org/model", detected_server: "llama.cpp", readme_flags: {}, downloaded: { "llama.cpp": true } });

  render(<MemoryRouter><App /></MemoryRouter>);

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/python serve/i);
  fireEvent.click(screen.getByText(/run benchmark/i));

  await waitFor(() => {
    const table = document.querySelector(".results-table") as HTMLElement | null;
    expect(table).not.toBeNull();
    expect(within(table!).getByText("42.0")).toBeInTheDocument();
  }, { timeout: 3000 });

  fireEvent.click(screen.getByRole("button", { name: "CLEAR" }));

  await waitFor(() => {
    expect(screen.queryByRole("button", { name: "CLEAR" })).not.toBeInTheDocument();
  });
  const table = document.querySelector(".results-table") as HTMLElement | null;
  expect(within(table!).queryByText("42.0")).not.toBeInTheDocument();
});

test("restores the latest completed run's results on load and shows CLEAR", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listRuns).mockResolvedValue({
    runs: [{ id: 3, repo_id: "org/model", requested_n: 1, created_at: "", status: "completed" }],
  });
  vi.mocked(api.getRun).mockResolvedValue({
    status: "completed",
    total: 1,
    results: [{
      config_id: 1,
      server_id: "llama.cpp",
      flag_conf: { "--max-model-len": "8192" },
      serving_command: "llama-server --hf-repo org/model --hf-file model.gguf --ctx-size 8192",
      prompt_processing_tps: 100.0,
      decode_tps: 42.0,
    }],
  });

  render(<MemoryRouter><App /></MemoryRouter>);

  await waitFor(() => {
    const table = document.querySelector(".results-table") as HTMLElement | null;
    expect(table).not.toBeNull();
    expect(within(table!).getByText("42.0")).toBeInTheDocument();
  });
  expect(screen.getByRole("button", { name: "CLEAR" })).toBeInTheDocument();
});

test("re-attaches to an active running run on load and streams it", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listRuns).mockResolvedValue({
    runs: [{ id: 7, repo_id: "org/model", requested_n: 2, created_at: "", status: "running" }],
  });
  vi.mocked(api.getRun).mockResolvedValue({
    status: "running",
    total: 2,
    results: [],
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await waitFor(() => expect(screen.getByText(/watching benchmark run #7 in progress/i)).toBeInTheDocument());
  await waitFor(() => expect(api.getRun).toHaveBeenCalledWith(7), { timeout: 3000 });
});

test("fetches speed-bench info on mount and passes it to the config bank", async () => {
  const { api } = await import("./api/client");
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  await waitFor(() => expect(api.getSpeedBenchInfo).toHaveBeenCalled());
});

test("multi-gguf: lists files as checkboxes, Download downloads only checked files", async () => {
  const { api } = await import("./api/client");
  const downloadModelSpy = vi.spyOn(api, "downloadModel").mockResolvedValue({ ok: true });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    gguf_files: [
      { path: "model.Q4_K_M.gguf", size: 4_000_000_000, fit: { stage: "gpu", warning: false, needed_gb: 7.1 } },
      { path: "model.Q8_0.gguf", size: 8_000_000_000, fit: { stage: "ram_offload", warning: false, needed_gb: 11.2 } },
    ],
    downloaded_ggufs: { "llama.cpp": [] },
    downloaded: { "llama.cpp": false },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  const checkboxes = screen.getAllByRole("checkbox");
  expect(checkboxes).toHaveLength(2);
  expect(screen.getByText(/File\(model\.Q4_K_M\.gguf\)/i)).toBeInTheDocument();
  expect(screen.getByText(/File\(model\.Q8_0\.gguf\)/i)).toBeInTheDocument();

  const downloadBtn = screen.getByRole("button", { name: "Download" });
  expect(downloadBtn).toBeDisabled();

  fireEvent.click(checkboxes[0]);
  expect(downloadBtn).not.toBeDisabled();
  fireEvent.click(downloadBtn);

  expect(downloadModelSpy).toHaveBeenCalledWith({
    repo_id: "org/model",
    server_id: "llama.cpp",
    gguf_filenames: ["model.Q4_K_M.gguf"],
  });
});

test("multi-gguf: already-downloaded files are marked and excluded from selection", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    gguf_files: [
      { path: "model.Q4_K_M.gguf", size: 4_000_000_000, fit: { stage: "gpu", warning: false, needed_gb: 7.1 } },
      { path: "model.Q8_0.gguf", size: 8_000_000_000, fit: { stage: "ram_offload", warning: false, needed_gb: 11.2 } },
    ],
    downloaded_ggufs: { "llama.cpp": ["model.Q4_K_M.gguf"] },
    downloaded: { "llama.cpp": true },
  });

  render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  const checkboxes = screen.getAllByRole("checkbox");
  expect(checkboxes[0]).toBeDisabled();
  expect(checkboxes[1]).not.toBeDisabled();
  expect(screen.getByText("GENERATE")).not.toBeDisabled();
});

test("multi-gguf: completed in-session download marks file downloaded and prevents re-download", async () => {
  const { api } = await import("./api/client");
  const { useDownloadProgress } = await import("./ws/useDownloadProgress");
  const downloadModelSpy = vi.spyOn(api, "downloadModel").mockResolvedValue({ ok: true });
  const listModelsSpy = vi.spyOn(api, "listModels");
  listModelsSpy
    .mockResolvedValueOnce({ models: [] })
    .mockResolvedValue({
      models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded", gguf_filename: "model.Q4_K_M.gguf" }],
    });
  vi.mocked(api.analyze).mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    gguf_files: [
      { path: "model.Q4_K_M.gguf", size: 4_000_000_000, fit: { stage: "gpu", warning: false, needed_gb: 7.1 } },
      { path: "model.Q8_0.gguf", size: 8_000_000_000, fit: { stage: "ram_offload", warning: false, needed_gb: 11.2 } },
    ],
    downloaded_ggufs: { "llama.cpp": [] },
    downloaded: { "llama.cpp": false },
  });
  vi.mocked(useDownloadProgress).mockReturnValue([]);

  const view = render(<MemoryRouter><App /></MemoryRouter>);
  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);

  const checkboxes = screen.getAllByRole("checkbox");
  expect(checkboxes[0]).not.toBeDisabled();
  expect(checkboxes[1]).not.toBeDisabled();
  fireEvent.click(checkboxes[0]); // check Q4_K_M

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_started", server_id: "llama.cpp", repo_id: "org/model", command: "hf download org/model" },
    { type: "download_log", server_id: "llama.cpp", repo_id: "org/model", line: "Fetching..." },
    { type: "download_done", server_id: "llama.cpp", repo_id: "org/model", local_path: "/cache/org/model/model.Q4_K_M.gguf" },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  // listModels refreshes asynchronously; Q4_K_M must flip to downloaded/disabled
  await waitFor(() => {
    const refreshed = screen.getAllByRole("checkbox");
    expect(refreshed[0]).toBeDisabled(); // Q4_K_M now downloaded, cannot re-select
    expect(refreshed[1]).not.toBeDisabled();
  });

  // Selection was cleared; user checks the remaining file only
  const downloadBtn = screen.getByRole("button", { name: "Download" });
  expect(downloadBtn).toBeDisabled();
  fireEvent.click(screen.getAllByRole("checkbox")[1]);
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  expect(downloadModelSpy).toHaveBeenCalledTimes(1);
  expect(downloadModelSpy).toHaveBeenCalledWith({
    repo_id: "org/model",
    server_id: "llama.cpp",
    gguf_filenames: ["model.Q8_0.gguf"],
  });
});
