import { normalizeInput, api } from "./client";

test("normalizeInput sends raw value to analyze", () => {
  expect(normalizeInput(" https://huggingface.co/org/model ")).toBe("https://huggingface.co/org/model");
});

test("api.getServers returns readiness and hardware", async () => {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ readiness: { vllm: true }, hardware: {} })} as Response),
  );
  const data = await api.getServers();
  expect(data.readiness.vllm).toBe(true);
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
