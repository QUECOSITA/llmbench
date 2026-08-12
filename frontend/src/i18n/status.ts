import type { ParseKeys } from "i18next";
import i18n from "./index";

const STATUS_KEY: Record<string, ParseKeys> = {
  running: "status.running",
  queued: "status.queued",
  completed: "status.completed",
  failed: "status.failed",
  cancelled: "status.cancelled",
  error: "status.error",
  ok: "status.ok",
};

export function statusLabel(status: string | null | undefined): string {
  if (!status) return "";
  const key = STATUS_KEY[status];
  return key ? i18n.t(key) : status;
}
