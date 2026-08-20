import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { PendingDecision } from "../ws/useBenchmarkProgress";

interface Props {
  decision: PendingDecision;
  onSubmit: (tool: string, args: Record<string, unknown>) => void;
  onCancel: () => void;
}

export function DecisionModal({ decision, onSubmit, onCancel }: Props) {
  const { t } = useTranslation();
  const [tool, setTool] = useState<string>(decision.proposed_tool);
  const [argsText, setArgsText] = useState<string>(
    Object.keys(decision.proposed_args ?? {}).length > 0
      ? JSON.stringify(decision.proposed_args, null, 2)
      : "",
  );
  const [error, setError] = useState<string | null>(null);
  const options = decision.tool_options?.length ? decision.tool_options : [tool];

  const submit = () => {
    let args: Record<string, unknown> = {};
    const trimmed = argsText.trim();
    if (trimmed) {
      try {
        const parsed = JSON.parse(trimmed);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          throw new Error("args must be a JSON object");
        }
        args = parsed as Record<string, unknown>;
      } catch {
        setError(t("decision.invalidArgs"));
        return;
      }
    }
    setError(null);
    onSubmit(tool, args);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="decision-overlay"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
      }}
    >
      <div className="decision-modal" style={{ background: "var(--panel-bg,#101418)", border: "1px solid var(--hairline)", padding: 16, maxWidth: 480, width: "90%" }}>
        <div style={{ color: "var(--anode)", fontSize: 13, letterSpacing: 1, marginBottom: 8 }}>
          {t("decision.title")}
        </div>
        <div style={{ fontSize: 11, color: "var(--anode)", marginBottom: 12 }}>
          {t("decision.hint", { step: decision.index + 1 })}
        </div>
        <label style={{ display: "block", fontSize: 12, color: "var(--anode)", marginBottom: 6 }}>
          {t("decision.tool")}
          <select
            value={tool}
            onChange={(e) => setTool(e.target.value)}
            style={{ width: "100%", marginTop: 4 }}
          >
            {options.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </label>
        <label style={{ display: "block", fontSize: 12, color: "var(--anode)", marginBottom: 6 }}>
          {t("decision.args")}
          <textarea
            value={argsText}
            onChange={(e) => setArgsText(e.target.value)}
            rows={4}
            spellCheck={false}
            placeholder={t("decision.argsPlaceholder")}
            style={{ width: "100%", marginTop: 4, fontFamily: "var(--font-mono)", fontSize: 11 }}
          />
        </label>
        {error && <div style={{ color: "var(--accent)", fontSize: 11, marginBottom: 8 }}>{error}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="btn-neutral" onClick={onCancel}>{t("decision.cancel")}</button>
          <button onClick={submit}>{t("decision.continue")}</button>
        </div>
      </div>
    </div>
  );
}
