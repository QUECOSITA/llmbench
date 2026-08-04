import { useEffect, useRef, useState } from "react";

export interface DownloadEvent {
  type:
    | "download_started"
    | "download_log"
    | "download_progress"
    | "download_done"
    | "download_error"
    | "download_cancelled"
    | "prune_started"
    | "prune_log"
    | "prune_prompt"
    | "prune_done";
  server_id?: string;
  repo_id?: string;
  command?: string;
  line?: string;
  status?: string;
  local_path?: string;
  message?: string;
  accepted?: boolean;
}

export function useDownloadProgress(active: boolean) {
  const [events, setEvents] = useState<DownloadEvent[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!active) return;
    const ws = new WebSocket("ws://localhost:8000/api/ws");
    wsRef.current = ws;
    ws.onmessage = (msg) => {
      setEvents((prev) => [...prev, JSON.parse(msg.data) as DownloadEvent]);
    };
    return () => ws.close();
  }, [active]);

  return events;
}
