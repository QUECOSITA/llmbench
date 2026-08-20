import { useTranslation } from "react-i18next";
import type { FailureNotice } from "../ws/useBenchmarkProgress";

interface Props {
  notice: FailureNotice;
  onDismiss: () => void;
}

export function AgenticFailureNotice({ notice, onDismiss }: Props) {
  const { t } = useTranslation();
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      className="decision-overlay"
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 110,
      }}
    >
      <div
        className="decision-modal"
        style={{
          background: "var(--panel-bg,#101418)",
          border: "1px solid var(--accent)",
          padding: 16, maxWidth: 520, width: "92%",
        }}
      >
        <div style={{ color: "var(--accent)", fontSize: 13, letterSpacing: 1, marginBottom: 6 }}>
          {t("agentic.failureTitle", { tier: notice.tier ?? "" })}
        </div>
        <div style={{ fontSize: 12, color: "var(--anode)", lineHeight: 1.5, marginBottom: 10 }}>
          {notice.message}
        </div>
        {notice.details ? (
          <pre
            style={{
              whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 10,
              color: "var(--anode)", background: "rgba(0,0,0,0.35)",
              border: "1px solid var(--hairline)", padding: 8, maxHeight: 180,
              overflow: "auto", margin: "0 0 12px",
            }}
          >
            {notice.details}
          </pre>
        ) : null}
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button onClick={onDismiss}>{t("agentic.failureDismiss")}</button>
        </div>
      </div>
    </div>
  );
}
