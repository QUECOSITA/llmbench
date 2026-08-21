import { useEffect, useRef, useState } from "react";
import type { AgenticDetail } from "../components/AgenticDetailStrip";

export interface ProgressEvent {
  type: "run_started" | "config_start" | "config_done" | "run_done" | "run_sync" | "run_watch" | "bench_log" | "results_clear" | "agentic_decision" | "failure_dismiss" | "decision_clear";
  run_id?: number;
  index?: number;
  total?: number;
  config?: unknown;
  kind?: "line" | "progress";
  text?: string;
  result?: {
    status: string;
    decode_tps: number | null;
    prompt_processing_tps: number | null;
    agentic_tps: number | null;
    agentic_steps?: number | null;
    agentic_tool_calls?: number | null;
    agentic_plan_revisions?: number | null;
    agentic_avg_ms?: number | null;
    agentic_p95_ms?: number | null;
    total_prompt_tokens?: number | null;
    total_completion_tokens?: number | null;
    agentic_tier?: string | null;
    user_decisions?: number | null;
    failure_reason_key?: string | null;
    failure_reason?: string | null;
    output?: string;
  };
  flag_conf?: Record<string, string>;
  status?: string;
  results?: ResultRow[];
  proposed_tool?: string;
  proposed_args?: Record<string, unknown>;
  tool_options?: string[];
}

export interface ResultRow {
  server_id: string;
  flag_conf: Record<string, string>;
  prompt_processing_tps: number | null;
  decode_tps: number | null;
  agentic_tps: number | null;
  agentic_steps?: number | null;
  agentic_tool_calls?: number | null;
  agentic_plan_revisions?: number | null;
  agentic_avg_ms?: number | null;
  agentic_p95_ms?: number | null;
  total_prompt_tokens?: number | null;
  total_completion_tokens?: number | null;
  agentic_tier?: string | null;
  user_decisions?: number | null;
  failure_reason_key?: string | null;
  failure_reason?: string | null;
  result_status?: string | null;
}

export interface PendingDecision {
  run_id: number | null;
  index: number;
  proposed_tool: string;
  proposed_args: Record<string, unknown>;
  tool_options: string[];
}

export interface FailureNotice {
  key: string;
  message: string;
  tier: string | null;
  details?: string;
}

export interface ProgressState {
  running: boolean;
  runId: number | null;
  index: number;
  total: number;
  promptTps: number | null;
  decodeTps: number | null;
  agenticTps: number | null;
  agenticDetail: AgenticDetail | null;
  results: ResultRow[];
  lines: string[];
  currentCommand: string;
  pendingDecision: PendingDecision | null;
  lastFailure: FailureNotice | null;
}

export const INITIAL_STATE: ProgressState = {
  running: false,
  runId: null,
  index: 0,
  total: 0,
  promptTps: null,
  decodeTps: null,
  agenticTps: null,
  agenticDetail: null,
  results: [],
  lines: [],
  currentCommand: "",
  pendingDecision: null,
  lastFailure: null,
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
      agenticDetail: null,
      results: [],
      lines: [],
      currentCommand: "",
      pendingDecision: null,
      lastFailure: null,
    };
  }

  if (event.type === "results_clear") {
    return { ...state, results: [], promptTps: null, decodeTps: null, agenticTps: null, agenticDetail: null, pendingDecision: null, lastFailure: null };
  }

  if (event.type === "failure_dismiss") {
    return { ...state, lastFailure: null };
  }

  if (event.type === "decision_clear") {
    return { ...state, pendingDecision: null };
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

  if (event.type === "agentic_decision" && event.run_id === state.runId) {
    return {
      ...state,
      pendingDecision: {
        run_id: event.run_id ?? null,
        index: event.index ?? state.index,
        proposed_tool: event.proposed_tool ?? "finish",
        proposed_args: event.proposed_args ?? {},
        tool_options: event.tool_options ?? [],
      },
    };
  }

  if (event.type === "config_done" && event.run_id === state.runId) {
    const idx = event.index ?? state.index;
    const promptTps = event.result?.prompt_processing_tps ?? null;
    const decodeTps = event.result?.decode_tps ?? null;
    const agenticTps = event.result?.agentic_tps ?? null;
    const detail: AgenticDetail = {
      steps: event.result?.agentic_steps ?? null,
      toolCalls: event.result?.agentic_tool_calls ?? null,
      planRevisions: event.result?.agentic_plan_revisions ?? null,
      avgMs: event.result?.agentic_avg_ms ?? null,
      p95Ms: event.result?.agentic_p95_ms ?? null,
      totalPromptTokens: event.result?.total_prompt_tokens ?? null,
      totalCompletionTokens: event.result?.total_completion_tokens ?? null,
      tier: event.result?.agentic_tier ?? null,
    };
    const newResult: ResultRow = {
      server_id: "",
      flag_conf: event.flag_conf ?? {},
      prompt_processing_tps: promptTps,
      decode_tps: decodeTps,
      agentic_tps: agenticTps,
      agentic_steps: detail.steps,
      agentic_tool_calls: detail.toolCalls,
      agentic_plan_revisions: detail.planRevisions,
      agentic_avg_ms: detail.avgMs,
      agentic_p95_ms: detail.p95Ms,
      total_prompt_tokens: detail.totalPromptTokens,
      total_completion_tokens: detail.totalCompletionTokens,
      agentic_tier: event.result?.agentic_tier ?? null,
      user_decisions: event.result?.user_decisions ?? null,
      failure_reason_key: event.result?.failure_reason_key ?? null,
      failure_reason: event.result?.failure_reason ?? null,
      result_status: event.result?.status ?? null,
    };
    const results = [...state.results];
    results[idx] = newResult;
    const fmt = (v: number | null) => (v == null ? "—" : v.toFixed(1));
    const failureLine = event.result?.failure_reason
      ? ` · ${event.result.failure_reason}`
      : "";
    const resultLine = `PROMPT ${fmt(promptTps)} · DECODE ${fmt(decodeTps)} · AGENTIC ${fmt(agenticTps)} · ${event.result?.status ?? ""}${failureLine}`;
    const lastFailure = event.result?.failure_reason_key
      ? {
          key: event.result.failure_reason_key,
          message: event.result.failure_reason ?? "agentic config failed",
          tier: event.result.agentic_tier ?? null,
          details: (event.result.output ?? "").slice(-800),
        }
      : state.lastFailure;
    return {
      ...state,
      index: idx,
      total: event.total ?? state.total,
      promptTps,
      decodeTps,
      agenticTps,
      agenticDetail: detail,
      results,
      lines: [...state.lines, resultLine],
      pendingDecision: null,
      lastFailure,
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
      agenticDetail: last ? rowDetail(last) : null,
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
      agenticDetail: last ? rowDetail(last) : null,
      results,
      lines: state.lines,
      currentCommand: state.currentCommand,
      pendingDecision: state.pendingDecision,
      lastFailure: state.lastFailure,
    };
  }

  return state;
}

function rowDetail(row: ResultRow): AgenticDetail {
  return {
    steps: row.agentic_steps ?? null,
    toolCalls: row.agentic_tool_calls ?? null,
    planRevisions: row.agentic_plan_revisions ?? null,
    avgMs: row.agentic_avg_ms ?? null,
    p95Ms: row.agentic_p95_ms ?? null,
    totalPromptTokens: row.total_prompt_tokens ?? null,
    totalCompletionTokens: row.total_completion_tokens ?? null,
    tier: row.agentic_tier ?? null,
  };
}

export function useBenchmarkProgress() {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/api/ws");
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      setEvents((prev) => [...prev, JSON.parse(msg.data) as ProgressEvent]);
    };
    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, []);

  const sendDecision = (tool: string, args: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "agentic_decision_reply", tool, args }));
    }
  };

  return { events, sendDecision };
}
