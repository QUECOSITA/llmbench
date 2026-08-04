import type { DownloadEvent } from "./useDownloadProgress";

export type DownloadStatusType =
  | "downloading"
  | "downloaded"
  | "error"
  | "cancelled"
  | "pruning"
  | "pruned";

export interface DownloadStatus {
  status: DownloadStatusType;
  command: string;
  lines: string[];
  waitingInput: boolean;
  pruneAccepted: boolean | null;
  progress: boolean;
  message?: string;
  local_path?: string;
}

export interface DownloadState {
  [key: string]: DownloadStatus;
}

export function key(serverId: string, repoId: string): string {
  return `${serverId}::${repoId}`;
}

export function downloadActive(state: DownloadState): boolean {
  return Object.values(state).some(
    (d) => d.status === "downloading" || d.status === "cancelled" || d.status === "pruning",
  );
}

const IDLE: DownloadStatus = {
  status: "downloading",
  command: "",
  lines: [],
  waitingInput: false,
  pruneAccepted: null,
  progress: false,
};

export function downloadReducer(state: DownloadState, event: DownloadEvent): DownloadState {
  if (!event.server_id || !event.repo_id) return state;
  const k = key(event.server_id, event.repo_id);
  const cur: DownloadStatus = state[k] ?? { ...IDLE };
  switch (event.type) {
    case "download_started":
      return { ...state, [k]: { ...cur, status: "downloading", command: event.command ?? "", lines: [], progress: false } };
    case "download_log":
      return { ...state, [k]: { ...cur, lines: [...cur.lines, event.line ?? ""], progress: false } };
    case "download_progress": {
      const lines = cur.progress ? [...cur.lines] : [...cur.lines, ""];
      lines[lines.length - 1] = event.line ?? "";
      return { ...state, [k]: { ...cur, lines, progress: true } };
    }
    case "download_done":
      return { ...state, [k]: { ...cur, status: "downloaded", local_path: event.local_path } };
    case "download_error":
      return { ...state, [k]: { ...cur, status: "error", message: event.message } };
    case "download_cancelled":
      return { ...state, [k]: { ...cur, status: "cancelled" } };
    case "prune_started":
      return { ...state, [k]: { ...cur, status: "pruning", command: event.command ?? cur.command } };
    case "prune_log":
      return { ...state, [k]: { ...cur, lines: [...cur.lines, event.line ?? ""] } };
    case "prune_prompt":
      return { ...state, [k]: { ...cur, waitingInput: true } };
    case "prune_done":
      return {
        ...state,
        [k]: {
          ...cur,
          status: "pruned",
          waitingInput: false,
          pruneAccepted: event.accepted ?? false,
          message: event.message,
        },
      };
    default:
      return state;
  }
}
