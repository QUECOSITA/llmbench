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

beforeEach(() => {
  FakeWS.instances = [];
});

test("useDownloadProgress connects on mount and collects events", () => {
  const orig = globalThis.WebSocket;
  (globalThis as { WebSocket: unknown }).WebSocket = FakeWS;
  try {
    const { result } = renderHook(() => useDownloadProgress());
    expect(FakeWS.instances).toHaveLength(1);
    const ws = FakeWS.instances[0];
    act(() => {
      ws.emit({ type: "download_log", server_id: "llama.cpp", repo_id: "org/model", line: "Fetching" });
      ws.emit({ type: "download_done", server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" });
    });
    const events = result.current as DownloadEvent[];
    expect(events).toHaveLength(2);
    expect(events[0].type).toBe("download_log");
    expect(events[1].type).toBe("download_done");
  } finally {
    (globalThis as { WebSocket: unknown }).WebSocket = orig;
  }
});

test("useDownloadProgress stays connected across renders and closes only on unmount", () => {
  const orig = globalThis.WebSocket;
  (globalThis as { WebSocket: unknown }).WebSocket = FakeWS;
  try {
    const { rerender, unmount } = renderHook(() => useDownloadProgress());
    expect(FakeWS.instances).toHaveLength(1);
    const ws = FakeWS.instances[0];
    rerender();
    expect(FakeWS.instances).toHaveLength(1);
    expect(ws.closed).toBe(false);
    unmount();
    expect(ws.closed).toBe(true);
  } finally {
    (globalThis as { WebSocket: unknown }).WebSocket = orig;
  }
});
