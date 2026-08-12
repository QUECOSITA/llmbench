import { normalizeInput, api, ApiError } from "./client";

test("normalizeInput sends raw value to analyze", () => {
  expect(normalizeInput(" https://huggingface.co/org/model ")).toBe("https://huggingface.co/org/model");
});

test("api.getServers returns readiness and hardware", async () => {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ readiness: { "llama.cpp": true }, hardware: {} })} as Response),
  );
  const data = await api.getServers();
  expect(data.readiness["llama.cpp"]).toBe(true);
});

test("api.removeModel deletes a repo with a single repo id arg", async () => {
  const fetchMock = vi.fn(
    (_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) } as Response),
  );
  globalThis.fetch = fetchMock;
  const data = await api.removeModel("org/model");
  expect(data.ok).toBe(true);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("http://localhost:8000/api/models/org%2Fmodel");
  expect((init as RequestInit).method).toBe("DELETE");
});

test("ApiError parses structured error body with context", async () => {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({
      ok: false,
      status: 409,
      json: () =>
        Promise.resolve({
          detail: "A benchmark is already running",
          context: { active_run: { id: 7, repo_id: "org/model", status: "running" } },
        }),
    } as Response),
  );

  await expect(api.startBenchmark({})).rejects.toMatchObject({
    status: 409,
    detail: "A benchmark is already running",
    context: { active_run: { id: 7, repo_id: "org/model", status: "running" } },
  });
  await expect(api.startBenchmark({})).rejects.toThrow(/409: A benchmark is already running/);
});

test("ApiError falls back to raw text when body is not JSON", async () => {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({
      ok: false,
      status: 503,
      text: () => Promise.resolve("service unavailable"),
    } as Response),
  );

  await expect(api.getServers()).rejects.toMatchObject({
    status: 503,
    detail: "service unavailable",
  });
  await expect(api.getServers()).rejects.toThrow(/503: service unavailable/);
});

test("api.clearRuns deletes the benchmark history", async () => {
  const fetchMock = vi.fn(
    (_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) } as Response),
  );
  globalThis.fetch = fetchMock;
  const data = await api.clearRuns();
  expect(data.ok).toBe(true);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("http://localhost:8000/api/benchmarks");
  expect((init as RequestInit).method).toBe("DELETE");
});
