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
    results: [{ server_id: "llama.cpp", flag_conf: {}, prompt_processing_tps: 10, decode_tps: 5, agentic_tps: null }],
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
    result: { status: "ok", decode_tps: 42.0, prompt_processing_tps: 100.0, agentic_tps: null },
  }));
  expect(next.index).toBe(0);
  expect(next.decodeTps).toBe(42.0);
  expect(next.promptTps).toBe(100.0);
  expect(next.results[0].decode_tps).toBe(42.0);
});

test("config_done keeps result_status on the row", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const next = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "failed", decode_tps: null, prompt_processing_tps: null, agentic_tps: null },
  }));
  expect(next.results[0].result_status).toBe("failed");
  expect(next.decodeTps).toBeNull();
});

test("config_done carries flag_conf into the result row when provided", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const next = progressReducer(state, ev("config_done", 1, {
    index: 0,
    flag_conf: { "--ctx-size": "54000" },
    result: { status: "ok", decode_tps: 42.0, prompt_processing_tps: 100.0, agentic_tps: null },
  }));
  expect(next.results[0].flag_conf).toEqual({ "--ctx-size": "54000" });
});

test("config_done defaults flag_conf to empty when not provided", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const next = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 42.0, prompt_processing_tps: 100.0, agentic_tps: null },
  }));
  expect(next.results[0].flag_conf).toEqual({});
});

test("config_done carries agentic_tps into live agenticTps and the result row", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const next = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 10.0, prompt_processing_tps: 100.0, agentic_tps: 25.0 },
  }));
  expect(next.agenticTps).toBe(25.0);
  expect(next.results[0].agentic_tps).toBe(25.0);
});

test("run_done for matching run_id stops running", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1));
  const next = progressReducer(state, ev("run_done", 1));
  expect(next.running).toBe(false);
});

test("run_sync replaces results and stops running", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 2 }));
  const next = progressReducer(state, {
    type: "run_sync",
    run_id: 1,
    status: "completed",
    total: 2,
    results: [
      { server_id: "llama.cpp", flag_conf: { "--max-model-len": "8192" }, prompt_processing_tps: 100.0, decode_tps: 42.0, agentic_tps: 25.0 },
    ],
  });
  expect(next.running).toBe(false);
  expect(next.results).toHaveLength(1);
  expect(next.results[0].decode_tps).toBe(42.0);
  expect(next.agenticTps).toBe(25.0);
  expect(next.index).toBe(1);
  expect(next.total).toBe(2);
});

test("run_sync for a different run_id is ignored", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1));
  const next = progressReducer(state, {
    type: "run_sync",
    run_id: 99,
    status: "failed",
    results: [],
  });
  expect(next.running).toBe(true);
  expect(next.results).toEqual([]);
});

test("events for different run_id are ignored (stale replay protection)", () => {
  // Run 1 starts
  const state1 = progressReducer(INITIAL_STATE, ev("run_started", 1));
  // Run 1 config_done
  const state2 = progressReducer(state1, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 10.0, prompt_processing_tps: null, agentic_tps: null },
  }));
  // Run 2 starts — should clear run 1 data
  const state3 = progressReducer(state2, ev("run_started", 2, { total: 1 }));
  // Run 1 config_done arrives late — should be ignored (run_id mismatch)
  const state4 = progressReducer(state3, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 10.0, prompt_processing_tps: null, agentic_tps: null },
  }));
  expect(state4.runId).toBe(2);
  expect(state4.results).toEqual([]);
  expect(state4.decodeTps).toBeNull();
});

test("run_started followed by late config_done (missed run_started) still works", () => {
  // Simulate a WS that missed run_started but got config_done
  const state1 = progressReducer(INITIAL_STATE, ev("config_done", 3, {
    index: 0,
    result: { status: "ok", decode_tps: 20.0, prompt_processing_tps: null, agentic_tps: null },
  }));
  // run_id is null, so config_done with run_id=3 is ignored (run_id mismatch)
  expect(state1.results).toEqual([]);
  // Now run_started for run 3 arrives
  const state2 = progressReducer(state1, ev("run_started", 3, { total: 1 }));
  expect(state2.runId).toBe(3);
  // Config done for run 3 now works
  const state3 = progressReducer(state2, ev("config_done", 3, {
    index: 0,
    result: { status: "ok", decode_tps: 20.0, prompt_processing_tps: null, agentic_tps: null },
  }));
  expect(state3.decodeTps).toBe(20.0);
  expect(state3.results.length).toBe(1);
});

test("results_clear empties results and live metrics", () => {
  let state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  state = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 42.0, prompt_processing_tps: 100.0, agentic_tps: null },
  }));
  expect(state.results).toHaveLength(1);
  const next = progressReducer(state, { type: "results_clear" });
  expect(next.results).toEqual([]);
  expect(next.promptTps).toBeNull();
  expect(next.decodeTps).toBeNull();
  expect(next.runId).toBe(1);
});

test("run_started clears lines and currentCommand", () => {
  const prev = {
    ...INITIAL_STATE,
    lines: ["old line"],
    waiting: false,
    currentCommand: "old cmd",
  };
  const next = progressReducer(prev, ev("run_started", 1, { total: 2 }));
  expect(next.lines).toEqual([]);
  expect(next.currentCommand).toBe("");
});

test("config_start appends a command header line", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 2 }));
  const next = progressReducer(state, {
    type: "config_start",
    run_id: 1,
    index: 0,
    total: 2,
    config: { bench_command: ["llama-bench", "-m", "x", "-o", "csv"] },
  });
  expect(next.lines).toEqual(["▸ config 1/2 — $ llama-bench -m x -o csv"]);
  expect(next.currentCommand).toBe("llama-bench -m x -o csv");
});

test("bench_log line appends and progress replaces the last line", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const withStart = progressReducer(state, {
    type: "config_start",
    run_id: 1,
    index: 0,
    total: 1,
    config: { bench_command: ["bench"] },
  });
  const withLine = progressReducer(withStart, {
    type: "bench_log", run_id: 1, index: 0, kind: "line", text: "loading...",
  });
  expect(withLine.lines[withLine.lines.length - 1]).toBe("loading...");
  const withProgress = progressReducer(withLine, {
    type: "bench_log", run_id: 1, index: 0, kind: "progress", text: "Loading: 50%",
  });
  expect(withProgress.lines).toEqual(["▸ config 1/1 — $ bench", "Loading: 50%"]);
});

test("config_done appends a result line", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const next = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: 42.0, prompt_processing_tps: 100.0, agentic_tps: null },
  }));
  expect(next.lines[next.lines.length - 1]).toContain("42.0");
  expect(next.lines[next.lines.length - 1]).toContain("100.0");
  expect(next.lines[next.lines.length - 1]).toContain("AGENTIC");
});

test("bench_log for a different run_id is ignored", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const next = progressReducer(state, {
    type: "bench_log", run_id: 99, index: 0, kind: "line", text: "stray",
  });
  expect(next.lines).toEqual([]);
});

test("config_start header numbering increments across configs", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 2 }));
  const first = progressReducer(state, {
    type: "config_start", run_id: 1, index: 0, total: 2, config: { bench_command: ["bench"] },
  });
  const second = progressReducer(first, {
    type: "config_start", run_id: 1, index: 1, total: 2, config: { bench_command: ["bench"] },
  });
  expect(first.lines).toEqual(["▸ config 1/2 — $ bench"]);
  expect(second.lines).toEqual(["▸ config 1/2 — $ bench", "▸ config 2/2 — $ bench"]);
});

test("run_watch seeds results and keeps running while a run is in progress", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 5, { total: 4 }));
  const next = progressReducer(state, {
    type: "run_watch",
    run_id: 5,
    status: "running",
    total: 4,
    results: [
      { server_id: "llama.cpp", flag_conf: { "--max-model-len": "8192" }, prompt_processing_tps: 100.0, decode_tps: 42.0, agentic_tps: 25.0 },
      { server_id: "llama.cpp", flag_conf: { "-c": "4096" }, prompt_processing_tps: 90.0, decode_tps: 38.0, agentic_tps: 20.0 },
    ],
  });
  expect(next.running).toBe(true);
  expect(next.runId).toBe(5);
  expect(next.index).toBe(2);
  expect(next.total).toBe(4);
  expect(next.results).toHaveLength(2);
  expect(next.results[1].decode_tps).toBe(38.0);
  expect(next.agenticTps).toBe(20.0);
});

test("run_watch for a different run_id is ignored", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 5));
  const next = progressReducer(state, {
    type: "run_watch",
    run_id: 99,
    status: "running",
    total: 1,
    results: [{ server_id: "llama.cpp", flag_conf: {}, prompt_processing_tps: 10, decode_tps: 5, agentic_tps: null }],
  });
  expect(next.runId).toBe(5);
  expect(next.results).toEqual([]);
});


test("agentic_decision sets pendingDecision with proposal and options", () => {
  const state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  const next = progressReducer(state, ev("agentic_decision", 1, {
    index: 0,
    proposed_tool: "read_file",
    proposed_args: { path: "/repo/main.py" },
    tool_options: ["read_file", "search", "finish"],
  }));
  expect(next.pendingDecision).toEqual({
    run_id: 1,
    index: 0,
    proposed_tool: "read_file",
    proposed_args: { path: "/repo/main.py" },
    tool_options: ["read_file", "search", "finish"],
  });
});

test("config_done clears pendingDecision and carries agentic_tier into result", () => {
  let state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  state = progressReducer(state, ev("agentic_decision", 1, {
    index: 0, proposed_tool: "read_file", proposed_args: {}, tool_options: [],
  }));
  const next = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "ok", decode_tps: null, prompt_processing_tps: null, agentic_tps: 25.0, agentic_tier: "heavy" },
  }));
  expect(next.pendingDecision).toBeNull();
  expect(next.results[0].agentic_tier).toBe("heavy");
});


test("config_done with a failure reason sets lastFailure with message and tier", () => {
  let state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  state = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: {
      status: "failed", decode_tps: null, prompt_processing_tps: null, agentic_tps: null,
      agentic_tier: "heavy",
      failure_reason_key: "context_overflow",
      failure_reason: "Context overflow: the injected filler + --ctx-size exceeds the model's context window.",
      output: "llama-server: request exceeds context",
    },
  }));
  expect(state.lastFailure).not.toBeNull();
  expect(state.lastFailure?.key).toBe("context_overflow");
  expect(state.lastFailure?.tier).toBe("heavy");
  expect(state.lastFailure?.message).toContain("Context overflow");
});

test("failure_dismiss clears lastFailure", () => {
  let state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  state = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "failed", decode_tps: null, prompt_processing_tps: null, agentic_tps: null, failure_reason_key: "unknown", failure_reason: "nope" },
  }));
  expect(state.lastFailure).not.toBeNull();
  state = progressReducer(state, { type: "failure_dismiss", run_id: 1 });
  expect(state.lastFailure).toBeNull();
});

test("run_started resets lastFailure", () => {
  let state = progressReducer(INITIAL_STATE, ev("run_started", 1, { total: 1 }));
  state = progressReducer(state, ev("config_done", 1, {
    index: 0,
    result: { status: "failed", decode_tps: null, prompt_processing_tps: null, agentic_tps: null, failure_reason_key: "unknown", failure_reason: "nope" },
  }));
  expect(state.lastFailure).not.toBeNull();
  state = progressReducer(state, ev("run_started", 2, { total: 1 }));
  expect(state.lastFailure).toBeNull();
});
