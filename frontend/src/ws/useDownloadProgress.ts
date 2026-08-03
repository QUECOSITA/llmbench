import { useEffect, useRef, useState } from "react";

export interface DownloadEvent {
  type: "download_started" | "download_log" | "download_done" | "download_error";
  server_id?: string;
  repo_id?: string;
  command?: string;
  line?: string;
  status?: string;
  local_path?: string;
  message?: string;
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
