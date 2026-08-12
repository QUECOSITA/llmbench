import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
  const label = progress ? t("run.configProgress", { index: progress.index + 1, total: progress.total }) : "";
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
      <span className="panel-cap">{t("panel.run")}</span>
      <div className="row">
        <button onClick={onRun} disabled={running || !canRun}>
          {t("common.runBenchmark")}
        </button>
        <span style={{ color: "var(--anode)", fontSize: 12 }}>{label}</span>
        <label style={{ color: "var(--anode)", fontSize: 12 }}>
          <input
            type="checkbox"
            checked={pause}
            disabled={running}
            onChange={(e) => onPauseChange(e.target.checked)}
          />
          {t("run.pause")}
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
                {t("run.pressEnter")}
              </span>
              <button className="btn-neutral" onClick={onContinue}>
                {t("run.continue")} ▸
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
