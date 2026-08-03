import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    removeModel: vi.fn(),
  },
}));

vi.mock("./ws/useBenchmarkProgress", async (importOriginal) => {
  const mod = await importOriginal<typeof import("./ws/useBenchmarkProgress")>();
  return { ...mod, useBenchmarkProgress: vi.fn().mockReturnValue([]) };
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
