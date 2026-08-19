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
  | "throughput"
  | "plain";

function classify(line: string): { kind: LineKind; text: string } {
  if (/^── step \d+\/\d+ ──$/.test(line)) return { kind: "step", text: line };
  if (line.startsWith("CHOICE ")) return { kind: "choice", text: line.slice(7) };
  if (line.startsWith("PROMPT ") && !/^PROMPT \d/.test(line)) return { kind: "prompt", text: line.slice(7) };
  if (line.startsWith("THINK ")) return { kind: "think", text: line.slice(6) };
  if (line.startsWith("BRANCH ")) return { kind: "branch", text: line.slice(7) };
  if (line.startsWith("TOOL ")) return { kind: "tool", text: line.slice(5) };
  if (line.startsWith("RESULT ")) return { kind: "result", text: line.slice(7) };
  if (line.startsWith("PLAN ")) return { kind: "plan", text: line.slice(5) };
  if (line.startsWith("FINISH ")) return { kind: "finish", text: line.slice(7) };
  if (line.startsWith("BUDGET ")) return { kind: "budget", text: line.slice(7) };
  if (/^step \d+\/\d+: prompt \d+ tok/.test(line)) return { kind: "throughput", text: line };
  return { kind: "plain", text: line };
}

export function AgenticSessionPanel({ lines }: { lines: string[] }) {
  const { t } = useTranslation();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const rows = lines
    .map((line, i) => ({ key: i, ...classify(line) }))
    .filter((r) => r.kind !== "plain");

  if (rows.length === 0) return null;

  return (
    <div className="agentic-session">
      <div className="agentic-session-head">{t("panel.agenticSession")}</div>
      <div className="agentic-session-body" ref={boxRef}>
        {rows.map((row) => (
          <div key={row.key} className={`agentic-line agentic-${row.kind}`}>
            <span className="agentic-tag">{row.kind}</span>
            <span className="agentic-text">{row.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
