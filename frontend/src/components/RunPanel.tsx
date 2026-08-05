import { useEffect, useRef } from "react";
import { MetricsBanks } from "./MetricsBanks";

interface Progress {
  index: number;
  total: number;
  promptTps?: number | null;
  decodeTps?: number | null;
}

interface Props {
  running: boolean;
  onRun: () => void;
  progress: Progress | null;
  canRun?: boolean;
  lines: string[];
  currentCommand: string;
  waiting: boolean;
  pause: boolean;
  onPauseChange: (paused: boolean) => void;
  onContinue: () => void;
}

export function RunPanel({
  running,
  onRun,
  progress,
  canRun = true,
  lines,
  currentCommand,
  waiting,
  pause,
  onPauseChange,
  onContinue,
}: Props) {
  const label = progress ? `config ${progress.index + 1}/${progress.total}` : "";
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  useEffect(() => {
    if (!waiting) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Enter") return;
      if (e.repeat) return;
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      onContinue();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [waiting, onContinue]);

  return (
    <section className="panel">
      <span className="panel-cap">03 · RUN</span>
      <div className="row">
        <button onClick={onRun} disabled={running || !canRun}>
          RUN BENCHMARK
        </button>
        <span style={{ color: "var(--anode)", fontSize: 12 }}>{label}</span>
        <label style={{ color: "var(--anode)", fontSize: 12 }}>
          <input
            type="checkbox"
            checked={pause}
            disabled={running}
            onChange={(e) => onPauseChange(e.target.checked)}
          />
          PAUSE
        </label>
      </div>
      <MetricsBanks
        promptTps={progress?.promptTps ?? null}
        decodeTps={progress?.decodeTps ?? null}
      />
      {lines.length > 0 && (
        <div className="dl-console">
          <div className="dl-console-head">$ {currentCommand}</div>
          <div className="dl-console-body" ref={boxRef}>
            {lines.map((line, i) => (
              <div key={i}>{line || "\u00a0"}</div>
            ))}
          </div>
          {waiting && (
            <div className="dl-console-actions">
              <span style={{ color: "var(--accent)", fontSize: 12 }}>
                PRESS ENTER TO CONTINUE
              </span>
              <button className="btn-neutral" onClick={onContinue}>
                CONTINUE ▸
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
