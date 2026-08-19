import { useEffect, useState } from "react";

export interface ProgressEvent {
  type: "run_started" | "config_start" | "config_done" | "run_done" | "run_sync" | "run_watch" | "bench_log" | "results_clear";
  run_id?: number;
  index?: number;
  total?: number;
  config?: unknown;
  kind?: "line" | "progress";
  text?: string;
  result?: { status: string; decode_tps: number | null; prompt_processing_tps: number | null; agentic_tps: number | null };
  flag_conf?: Record<string, string>;
  status?: string;
  results?: ResultRow[];
}

export interface ResultRow {
  server_id: string;
  flag_conf: Record<string, string>;
  prompt_processing_tps: number | null;
  decode_tps: number | null;
  agentic_tps: number | null;
  result_status?: string | null;
}

export interface ProgressState {
  running: boolean;
  runId: number | null;
  index: number;
  total: number;
  promptTps: number | null;
  decodeTps: number | null;
  agenticTps: number | null;
  results: ResultRow[];
  lines: string[];
  currentCommand: string;
}

export const INITIAL_STATE: ProgressState = {
  running: false,
  runId: null,
  index: 0,
  total: 0,
  promptTps: null,
  decodeTps: null,
  agenticTps: null,
  results: [],
  lines: [],
  currentCommand: "",
};

export function progressReducer(state: ProgressState, event: ProgressEvent): ProgressState {
  if (event.type === "run_started") {
    return {
      running: true,
      runId: event.run_id ?? null,
      index: 0,
      total: event.total ?? 0,
      promptTps: null,
      decodeTps: null,
      agenticTps: null,
      results: [],
      lines: [],
      currentCommand: "",
    };
  }

  if (event.type === "results_clear") {
    return { ...state, results: [], promptTps: null, decodeTps: null, agenticTps: null };
  }

  if (event.type === "config_start" && event.run_id === state.runId) {
    const cfg = event.config as { bench_command?: string[] } | undefined;
    const command = cfg?.bench_command?.join(" ") ?? "";
    const header = `▸ config ${(event.index ?? state.index) + 1}/${event.total ?? state.total} — $ ${command}`;
    return {
      ...state,
      index: event.index ?? state.index,
      total: event.total ?? state.total,
      currentCommand: command,
      lines: [...state.lines, header],
    };
  }

  if (event.type === "bench_log" && event.run_id === state.runId) {
    const text = event.text ?? "";
    const lines =
      event.kind === "progress" && state.lines.length > 0
        ? [...state.lines.slice(0, -1), text]
        : [...state.lines, text];
    return { ...state, lines };
  }

  if (event.type === "config_done" && event.run_id === state.runId) {
    const idx = event.index ?? state.index;
    const promptTps = event.result?.prompt_processing_tps ?? null;
    const decodeTps = event.result?.decode_tps ?? null;
    const agenticTps = event.result?.agentic_tps ?? null;
    const newResult: ResultRow = {
      server_id: "",
      flag_conf: event.flag_conf ?? {},
      prompt_processing_tps: promptTps,
      decode_tps: decodeTps,
      agentic_tps: agenticTps,
      result_status: event.result?.status ?? null,
    };
    const results = [...state.results];
    results[idx] = newResult;
    const fmt = (v: number | null) => (v == null ? "—" : v.toFixed(1));
    const resultLine = `PROMPT ${fmt(promptTps)} · DECODE ${fmt(decodeTps)} · AGENTIC ${fmt(agenticTps)} · ${event.result?.status ?? ""}`;
    return {
      ...state,
      index: idx,
      total: event.total ?? state.total,
      promptTps,
      decodeTps,
      agenticTps,
      results,
      lines: [...state.lines, resultLine],
    };
  }

  if (event.type === "run_done" && event.run_id === state.runId) {
    return { ...state, running: false };
  }

  if (event.type === "run_watch" && event.run_id === state.runId) {
    const results = event.results ?? [];
    const last = results[results.length - 1];
    return {
      ...state,
      running: true,
      runId: event.run_id,
      index: results.length,
      total: event.total ?? state.total,
      promptTps: last?.prompt_processing_tps ?? null,
      decodeTps: last?.decode_tps ?? null,
      agenticTps: last?.agentic_tps ?? null,
      results,
    };
  }

  if (event.type === "run_sync" && event.run_id === state.runId) {
    const results = event.results ?? [];
    const last = results[results.length - 1];
    return {
      running: false,
      runId: event.run_id,
      index: results.length,
      total: event.total ?? state.total,
      promptTps: last?.prompt_processing_tps ?? null,
      decodeTps: last?.decode_tps ?? null,
      agenticTps: last?.agentic_tps ?? null,
      results,
      lines: state.lines,
      currentCommand: state.currentCommand,
    };
  }

  return state;
}

export function useBenchmarkProgress() {
  const [events, setEvents] = useState<ProgressEvent[]>([]);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/api/ws");
    ws.onmessage = (msg) => {
      setEvents((prev) => [...prev, JSON.parse(msg.data) as ProgressEvent]);
    };
    return () => ws.close();
  }, []);

  return events;
}
