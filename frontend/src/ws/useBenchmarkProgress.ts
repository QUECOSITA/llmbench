import { useEffect, useState } from "react";

export interface ProgressEvent {
  type: "run_started" | "config_start" | "config_done" | "run_done" | "run_sync";
  run_id: number;
  index?: number;
  total?: number;
  config?: unknown;
  result?: { status: string; decode_tps: number | null; prompt_processing_tps: number | null };
  status?: string;
  results?: ResultRow[];
}

export interface ResultRow {
  server_id: string;
  flag_conf: Record<string, string>;
  prompt_processing_tps: number | null;
  decode_tps: number | null;
  result_status?: string | null;
}

export interface ProgressState {
  running: boolean;
  runId: number | null;
  index: number;
  total: number;
  promptTps: number | null;
  decodeTps: number | null;
  results: ResultRow[];
}

export const INITIAL_STATE: ProgressState = {
  running: false,
  runId: null,
  index: 0,
  total: 0,
  promptTps: null,
  decodeTps: null,
  results: [],
};

export function progressReducer(state: ProgressState, event: ProgressEvent): ProgressState {
  if (event.type === "run_started") {
    return {
      running: true,
      runId: event.run_id,
      index: 0,
      total: event.total ?? 0,
      promptTps: null,
      decodeTps: null,
      results: [],
    };
  }

  if (event.type === "config_start" && event.run_id === state.runId) {
    return { ...state, index: event.index ?? state.index };
  }

  if (event.type === "config_done" && event.run_id === state.runId) {
    const idx = event.index ?? state.index;
    const promptTps = event.result?.prompt_processing_tps ?? null;
    const decodeTps = event.result?.decode_tps ?? null;
    const newResult: ResultRow = {
      server_id: "",
      flag_conf: {},
      prompt_processing_tps: promptTps,
      decode_tps: decodeTps,
      result_status: event.result?.status ?? null,
    };
    const results = [...state.results];
    results[idx] = newResult;
    return {
      ...state,
      index: idx,
      total: event.total ?? state.total,
      promptTps: promptTps,
      decodeTps: decodeTps,
      results,
    };
  }

  if (event.type === "run_done" && event.run_id === state.runId) {
    return { ...state, running: false };
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
      results,
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
