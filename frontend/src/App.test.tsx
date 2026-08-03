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

test("fit warning banner renders when fit_verdict.warning is true", async () => {
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

  expect(await screen.findByText(/headroom tight/i)).toBeInTheDocument();
  expect(screen.getByText(/40\.5 GB/)).toBeInTheDocument();
});

test("fit warning banner absent when fit_verdict.warning is false", async () => {
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
  await screen.findByText(/org\/model/i);

  expect(screen.queryByText(/headroom tight/i)).not.toBeInTheDocument();
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
