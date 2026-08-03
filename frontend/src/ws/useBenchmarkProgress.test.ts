import { INITIAL_STATE, progressReducer } from "./useBenchmarkProgress";
import type { ProgressEvent } from "./useBenchmarkProgress";

function ev(type: ProgressEvent["type"], runId: number, extra?: Partial<ProgressEvent>): ProgressEvent {
  return { type, run_id: runId, ...extra };
}

test("run_started initializes state and clears previous results", () => {
  const prev = {
    ...INITIAL_STATE,
    running: true,
    runId: 1,
    results: [{ server_id: "vllm", flag_conf: {}, prompt_processing_tps: 10, decode_tps: 5 }],
  };
  const next = progressReducer(prev, ev("run_started", 2, { total: 3 }));
  expect(next.running).toBe(true);
  expect(next.runId).toBe(2);
  expect(next.total).toBe(3);
  expect(next.results).toEqual([]);
  expect(next.promptTps).toBeNull();
  expect(next.decodeTps).toBeNull();
});

test("config_done for matching run_id updates progress and results", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 2 }));
  const next = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 42.0, prompt_processing_tps: 100.0 },
  }));
  expect(next.index).toBe(0);
  expect(next.decodeTps).toBe(42.0);
  expect(next.promptTps).toBe(100.0);
  expect(next.results[0].decode_tps).toBe(42.0);
});

test("run_done for matching run_id stops running", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1));
  const next = progressReducer(state, ev("run_done", 1));
  expect(next.running).toBe(false);
});

test("events for different run_id are ignored (stale replay protection)", () => {
  // Run 1 starts
  const state1 = progressReducer(INITIAL_STATE, ev("run_started", 1));
  // Run 1 config_done
  const state2 = progressReducer(state1, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 10.0, prompt_processing_tps: null },
  }));
  // Run 2 starts — should clear run 1 data
  const state3 = progressReducer(state2, ev("run_started", 2, { total: 1 }));
  // Run 1 config_done arrives late — should be ignored (run_id mismatch)
  const state4 = progressReducer(state3, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 10.0, prompt_processing_tps: null },
  }));
  expect(state4.runId).toBe(2);
  expect(state4.results).toEqual([]);
  expect(state4.decodeTps).toBeNull();
});

test("run_started followed by late config_done (missed run_started) still works", () => {
  // Simulate a WS that missed run_started but got config_done
  const state1 = progressReducer(INITIAL_STATE, ev("config_done", 3, {
    index: 0,
    result: { status: "ok", decode_tps: 20.0, prompt_processing_tps: null },
  }));
  // run_id is null, so config_done with run_id=3 is ignored (run_id mismatch)
  expect(state1.results).toEqual([]);
  // Now run_started for run 3 arrives
  const state2 = progressReducer(state1, ev("run_started", 3, { total: 1 }));
  expect(state2.runId).toBe(3);
  // Config done for run 3 now works
  const state3 = progressReducer(state2, ev("config_done", 3, {
    index: 0,
    result: { status: "ok", decode_tps: 20.0, prompt_processing_tps: null },
  }));
  expect(state3.decodeTps).toBe(20.0);
  expect(state3.results.length).toBe(1);
});
