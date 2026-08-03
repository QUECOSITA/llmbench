import { useEffect, useRef, useState } from "react";

export interface ProgressEvent {
  type: "run_started" | "config_start" | "config_done" | "run_done";
  run_id: number;
  index?: number;
  total?: number;
  config?: unknown;
  result?: { status: string; decode_tps: number | null; prompt_processing_tps: number | null };
  status?: string;
}

export function useBenchmarkProgress(active: boolean) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!active) return;
    const ws = new WebSocket("ws://localhost:8000/api/ws");
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      setEvents((prev) => [...prev, JSON.parse(msg.data) as ProgressEvent]);
    };
    return () => ws.close();
  }, [active]);

  return events;
}
