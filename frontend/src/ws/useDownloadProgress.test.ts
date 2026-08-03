import { act, renderHook } from "@testing-library/react";
import { useDownloadProgress } from "./useDownloadProgress";
import type { DownloadEvent } from "./useDownloadProgress";

class FakeWS {
  static instances: FakeWS[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeWS.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

test("useDownloadProgress connects when active and collects events", () => {
  const orig = globalThis.WebSocket;
  (globalThis as { WebSocket: unknown }).WebSocket = FakeWS;
  try {
    const { result } = renderHook(() => useDownloadProgress(true));
    const ws = FakeWS.instances[FakeWS.instances.length - 1];
    act(() => {
      ws.emit({ type: "download_log", server_id: "vllm", repo_id: "org/model", line: "Fetching" });
      ws.emit({ type: "download_done", server_id: "vllm", repo_id: "org/model", status: "downloaded" });
    });
    const events = result.current as DownloadEvent[];
    expect(events).toHaveLength(2);
    expect(events[0].type).toBe("download_log");
    expect(events[1].type).toBe("download_done");
  } finally {
    (globalThis as { WebSocket: unknown }).WebSocket = orig;
  }
});

test("useDownloadProgress closes the socket when deactivated", () => {
  const orig = globalThis.WebSocket;
  (globalThis as { WebSocket: unknown }).WebSocket = FakeWS;
  try {
    const { rerender, unmount } = renderHook(({ active }) => useDownloadProgress(active), {
      initialProps: { active: true },
    });
    const ws = FakeWS.instances[FakeWS.instances.length - 1];
    rerender({ active: false });
    expect(ws.closed).toBe(true);
    unmount();
  } finally {
    (globalThis as { WebSocket: unknown }).WebSocket = orig;
  }
});
