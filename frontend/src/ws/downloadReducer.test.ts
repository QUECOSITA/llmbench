import { downloadActive, downloadReducer, key } from "./downloadReducer";
import type { DownloadEvent } from "./useDownloadProgress";

const ev = (type: DownloadEvent["type"], extra: Partial<DownloadEvent> = {}): DownloadEvent => ({
  type,
  server_id: "vllm",
  repo_id: "org/model",
  ...extra,
});

test("started sets downloading and command, resets lines", () => {
  let s = downloadReducer({}, ev("download_started", { command: "hf download org/model" }));
  expect(s["vllm::org/model"].status).toBe("downloading");
  expect(s["vllm::org/model"].command).toBe("hf download org/model");
  expect(key("vllm", "org/model")).toBe("vllm::org/model");
});

test("log appends and progress replaces the last line", () => {
  let s = downloadReducer({}, ev("download_started"));
  s = downloadReducer(s, ev("download_log", { line: "Fetching..." }));
  s = downloadReducer(s, ev("download_progress", { line: "45%" }));
  s = downloadReducer(s, ev("download_progress", { line: "100%" }));
  expect(s["vllm::org/model"].lines).toEqual(["Fetching...", "100%"]);
});

test("progress with no prior lines creates one line", () => {
  const s = downloadReducer({}, ev("download_progress", { line: "45%" }));
  expect(s["vllm::org/model"].lines).toEqual(["45%"]);
});

test("done and error set terminal states", () => {
  let s = downloadReducer({}, ev("download_started"));
  s = downloadReducer(s, ev("download_done", { local_path: "/x" }));
  expect(s["vllm::org/model"].status).toBe("downloaded");
  expect(s["vllm::org/model"].local_path).toBe("/x");
  let t = downloadReducer({}, ev("download_started"));
  t = downloadReducer(t, ev("download_error", { message: "boom" }));
  expect(t["vllm::org/model"].status).toBe("error");
  expect(t["vllm::org/model"].message).toBe("boom");
});

test("cancel then prune sequence keeps the console entry", () => {
  let s = downloadReducer({}, ev("download_started"));
  s = downloadReducer(s, ev("download_cancelled"));
  expect(s["vllm::org/model"].status).toBe("cancelled");
  s = downloadReducer(s, ev("prune_started", { command: "hf cache prune --format human" }));
  expect(s["vllm::org/model"].status).toBe("pruning");
  s = downloadReducer(s, ev("prune_log", { line: "About to delete 1 incomplete download(s)." }));
  s = downloadReducer(s, ev("prune_prompt"));
  expect(s["vllm::org/model"].waitingInput).toBe(true);
  s = downloadReducer(s, ev("prune_done", { accepted: true }));
  expect(s["vllm::org/model"].status).toBe("pruned");
  expect(s["vllm::org/model"].pruneAccepted).toBe(true);
  expect(s["vllm::org/model"].waitingInput).toBe(false);
});

test("downloadActive is true while downloading/cancelled/pruning", () => {
  let s = downloadReducer({}, ev("download_started"));
  expect(downloadActive(s)).toBe(true);
  s = downloadReducer(s, ev("download_cancelled"));
  expect(downloadActive(s)).toBe(true);
  s = downloadReducer(s, ev("prune_started"));
  expect(downloadActive(s)).toBe(true);
  s = downloadReducer(s, ev("prune_done", { accepted: false }));
  expect(downloadActive(s)).toBe(false);
  expect(downloadActive({})).toBe(false);
});

test("events without server/repo are ignored", () => {
  const s = downloadReducer({}, { type: "download_log", line: "x" } as DownloadEvent);
  expect(s).toEqual({});
});
