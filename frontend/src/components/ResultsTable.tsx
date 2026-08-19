import { useTranslation } from "react-i18next";
import { statusLabel } from "../i18n/status";
import { AgenticDetailStrip } from "./AgenticDetailStrip";

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
  result_status?: string | null;
}

const failed = (s?: string | null) => Boolean(s) && s !== "ok";

export function ResultsTable({ rows }: { rows: ResultRow[] }) {
  const { t } = useTranslation();
  const sorted = [...rows].sort(
    (a, b) => (b.agentic_tps ?? b.decode_tps ?? -1) - (a.agentic_tps ?? a.decode_tps ?? -1),
  );
  const flagNames = [...new Set(sorted.flatMap((r) => Object.keys(r.flag_conf)))];
  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>#</th>
          <th>{t("results.program")}</th>
          {flagNames.map((f) => <th key={f}>{f}</th>)}
          <th>{t("results.promptTps")}</th>
          <th>{t("results.decodeTps")}</th>
          <th>{t("results.agenticTps")}</th>
          <th>{t("results.status")}</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r, i) => (
          <tr key={i} className={i === 0 ? "row-best" : ""}>
            <td>{i + 1}</td>
            <td>{r.server_id}</td>
            {flagNames.map((f) => <td key={f}>{r.flag_conf[f] ?? "—"}</td>)}
            <td>{r.prompt_processing_tps?.toFixed(1) ?? "—"}</td>
            <td className={i === 0 && r.agentic_tps == null ? "digit-best" : ""}>{r.decode_tps?.toFixed(1) ?? "—"}</td>
            <td className={i === 0 && r.agentic_tps != null ? "digit-best" : ""}>
              {r.agentic_tps?.toFixed(1) ?? "—"}
              <AgenticDetailStrip
                steps={r.agentic_steps ?? null}
                toolCalls={r.agentic_tool_calls ?? null}
                planRevisions={r.agentic_plan_revisions ?? null}
                avgMs={r.agentic_avg_ms ?? null}
                p95Ms={r.agentic_p95_ms ?? null}
                totalPromptTokens={r.total_prompt_tokens ?? null}
                totalCompletionTokens={r.total_completion_tokens ?? null}
              />
            </td>
            <td className={failed(r.result_status) ? "status-failed" : ""}>
              {failed(r.result_status) ? statusLabel(r.result_status) : ""}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
