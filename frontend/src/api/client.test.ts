import { normalizeInput, api } from "./client";

test("normalizeInput sends raw value to analyze", () => {
  expect(normalizeInput(" https://huggingface.co/org/model ")).toBe("https://huggingface.co/org/model");
});

test("api.getServers returns readiness and hardware", async () => {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ readiness: { vllm: true }, hardware: {} }) } as Response),
  );
  const data = await api.getServers();
  expect(data.readiness.vllm).toBe(true);
});
