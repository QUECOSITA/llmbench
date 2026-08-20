import { useTranslation } from "react-i18next";

export interface AgenticDetail {
  steps: number | null;
  toolCalls: number | null;
  planRevisions: number | null;
  avgMs: number | null;
  p95Ms: number | null;
  totalPromptTokens: number | null;
  totalCompletionTokens: number | null;
  tier?: string | null;
}

export function AgenticDetailStrip({
  steps,
  toolCalls,
  planRevisions,
  avgMs,
  p95Ms,
  totalPromptTokens,
  totalCompletionTokens,
  tier,
}: AgenticDetail) {
  const { t } = useTranslation();
  const parts: string[] = [];
  if (tier != null) parts.push(`tier ${tier}`);
  if (steps != null) parts.push(t("metrics.agenticSteps", { count: steps }));
  if (toolCalls != null) parts.push(t("metrics.agenticToolCalls", { count: toolCalls }));
  if (planRevisions != null) parts.push(t("metrics.agenticPlanRevs", { count: planRevisions }));
  if (avgMs != null) parts.push(t("metrics.agenticAvg", { s: (avgMs / 1000).toFixed(1) }));
  if (p95Ms != null) parts.push(t("metrics.agenticP95", { s: (p95Ms / 1000).toFixed(1) }));
  const ctx = totalPromptTokens != null && totalCompletionTokens != null
    ? totalPromptTokens + totalCompletionTokens
    : null;
  if (ctx != null) parts.push(t("metrics.agenticCtx", { k: (ctx / 1000).toFixed(1) }));
  if (parts.length === 0) return null;
  return (
    <div className="agentic-detail" style={{ fontSize: 10, color: "var(--anode)", letterSpacing: 0.5 }}>
      {parts.join(" · ")}
    </div>
  );
}
