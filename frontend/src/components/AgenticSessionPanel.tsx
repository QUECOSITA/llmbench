import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

type LineKind =
  | "step"
  | "choice"
  | "prompt"
  | "think"
  | "branch"
  | "tool"
  | "result"
  | "plan"
  | "finish"
  | "budget"
  | "plain";

function classify(line: string): { kind: LineKind; text: string } {
  if (/^── step \d+\/\d+ ──$/.test(line)) return { kind: "step", text: line };
  if (line.startsWith("CHOICE ")) return { kind: "choice", text: line.slice(7) };
  if (line.startsWith("PROMPT ")) return { kind: "prompt", text: line.slice(7) };
  if (line.startsWith("THINK ")) return { kind: "think", text: line.slice(6) };
  if (line.startsWith("BRANCH ")) return { kind: "branch", text: line.slice(7) };
  if (line.startsWith("TOOL ")) return { kind: "tool", text: line.slice(5) };
  if (line.startsWith("RESULT ")) return { kind: "result", text: line.slice(7) };
  if (line.startsWith("PLAN ")) return { kind: "plan", text: line.slice(5) };
  if (line.startsWith("FINISH ")) return { kind: "finish", text: line.slice(7) };
  if (line.startsWith("BUDGET ")) return { kind: "budget", text: line.slice(7) };
  return { kind: "plain", text: line };
}

export function AgenticSessionPanel({ lines }: { lines: string[] }) {
  const { t } = useTranslation();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  if (lines.length === 0) return null;

  return (
    <div className="agentic-session">
      <div className="agentic-session-head">{t("panel.agenticSession")}</div>
      <div className="agentic-session-body" ref={boxRef}>
        {lines.map((line, i) => {
          const { kind, text } = classify(line);
          return (
            <div key={i} className={`agentic-line agentic-${kind}`}>
              <span className="agentic-tag">{kind}</span>
              <span className="agentic-text">{text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
