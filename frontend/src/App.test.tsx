import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { App } from "./App";

vi.mock("./api/client", () => ({
  api: {
    getServers: vi.fn().mockResolvedValue({ readiness: {}, hardware: {} }),
    listModels: vi.fn().mockResolvedValue({ models: [] }),
    listRuns: vi.fn().mockResolvedValue({ runs: [] }),
    analyze: vi.fn().mockResolvedValue({ repo_id: "org/model", detected_server: "vllm", readme_flags: {} }),
    generateConfigs: vi.fn().mockResolvedValue({
      configs: [{ flags: { "--n-gpu": "1" }, serving_command: "python serve.py", bench_command: [] }],
    }),
    startBenchmark: vi.fn().mockResolvedValue({ run_id: 1 }),
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

test("LOAD on a downloaded row fills MODEL INPUT and analyzes", async () => {
  const { api } = await import("./api/client");
  vi.mocked(api.listModels).mockResolvedValue({
    models: [{ server_id: "vllm", repo_id: "org/model", status: "downloaded" }],
  });
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValue({ repo_id: "org/model", detected_server: "vllm", readme_flags: {} });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  await screen.findByText("vLLM");
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
  analyzeSpy.mockResolvedValue({ repo_id: "org/model", detected_server: "llama.cpp", readme_flags: {} });

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
      models: [{ server_id: "vllm", repo_id: "org/model", status: "downloaded" }],
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

test("fit line renders NO FIT when verdict is no_fit", async () => {
  const { api } = await import("./api/client");
  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "vllm",
    readme_flags: {},
    fit_verdict: { stage: "no_fit", warning: true, needed_gb: 40.5 },
    hardware: { gpu_vram_gb: 8, ram_total_gb: 32, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": false, vllm: false, sglang: false },
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
    detected_server: "vllm",
    readme_flags: {},
    fit_verdict: { stage: "gpu", warning: false, needed_gb: 3.8 },
    hardware: { gpu_vram_gb: 24, ram_total_gb: 64, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": false, vllm: false, sglang: false },
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
    detected_server: "vllm",
    readme_flags: {},
    fit_verdict: { stage: "ram_offload", warning: false, needed_gb: 14.2 },
    hardware: { gpu_vram_gb: 8, ram_total_gb: 64, gpu_name: "RTX 4090" },
    downloaded: { "llama.cpp": false, vllm: false, sglang: false },
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

  const downloadBtn = within(screen.getByText("vllm:").closest("span")!).getByText("Download");
  fireEvent.click(downloadBtn);
  expect(await screen.findByText(/downloading/i)).toBeInTheDocument();
  expect(downloadModelSpy).toHaveBeenCalledWith({ repo_id: "org/model", server_id: "vllm" });

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_log", server_id: "vllm", repo_id: "org/model", line: "Fetching..." },
    { type: "download_done", server_id: "vllm", repo_id: "org/model", status: "downloaded", local_path: "/x" },
  ]);
  view.rerender(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  expect(await screen.findByText("downloaded")).toBeInTheDocument();
  await waitFor(() => expect(api.listModels).toHaveBeenCalledTimes(2));
});

test("download for direct file link passes the single gguf filename", async () => {
  const { api } = await import("./api/client");
  const downloadModelSpy = vi.spyOn(api, "downloadModel");
  downloadModelSpy.mockResolvedValueOnce({ ok: true });

  const analyzeSpy = vi.spyOn(api, "analyze");
  analyzeSpy.mockResolvedValueOnce({
    repo_id: "org/model",
    detected_server: "llama.cpp",
    readme_flags: {},
    gguf_files: [{ path: "model.Q4_K_M.gguf", size: 4_000_000_000 }],
    downloaded: { "llama.cpp": false, vllm: false, sglang: false },
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
    gguf_filename: "model.Q4_K_M.gguf",
  });
});

test("cancel flow: CANCEL shows prune prompt, answering y completes", async () => {
  const { api } = await import("./api/client");
  const { useDownloadProgress } = await import("./ws/useDownloadProgress");
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

  fireEvent.click(within(screen.getByText("vllm:").closest("span")!).getByText("Download"));
  expect(await screen.findByRole("button", { name: /cancel/i })).toBeInTheDocument();

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_started", server_id: "vllm", repo_id: "org/model", command: "hf download org/model" },
    { type: "download_log", server_id: "vllm", repo_id: "org/model", line: "Fetching..." },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(cancelSpy).toHaveBeenCalled();

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "download_cancelled", server_id: "vllm", repo_id: "org/model" },
    { type: "prune_started", server_id: "vllm", repo_id: "org/model", command: "hf cache prune --format human" },
    { type: "prune_log", server_id: "vllm", repo_id: "org/model", line: "About to delete 1 incomplete download(s)." },
    { type: "prune_prompt", server_id: "vllm", repo_id: "org/model" },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  const yBtn = screen.getByRole("button", { name: "y" });
  fireEvent.click(yBtn);
  expect(pruneSpy).toHaveBeenCalledWith("y");

  vi.mocked(useDownloadProgress).mockReturnValue([
    { type: "prune_done", server_id: "vllm", repo_id: "org/model", accepted: true },
  ]);
  view.rerender(<MemoryRouter><App /></MemoryRouter>);

  expect(await screen.findByText(/cache pruned/i)).toBeInTheDocument();
  const span = within(screen.getByText("vllm:").closest("span")!);
  expect(span.getByRole("button", { name: /^download$/i })).toBeInTheDocument();
});
