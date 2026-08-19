import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { MetricsBanks } from "./MetricsBanks";

interface Progress {
  index: number;
  total: number;
  promptTps?: number | null;
  decodeTps?: number | null;
  agenticTps?: number | null;
}

interface Props {
  running: boolean;
  onRun: () => void;
  onCancel?: () => void;
  progress: Progress | null;
  canRun?: boolean;
  lines: string[];
  currentCommand: string;
}

export function RunPanel({
  running,
  onRun,
  onCancel,
  progress,
  canRun = true,
  lines,
  currentCommand,
}: Props) {
  const { t } = useTranslation();
  const label = progress ? t("run.configProgress", { index: progress.index + 1, total: progress.total }) : "";
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <section className="panel">
      <span className="panel-cap">{t("panel.run")}</span>
      <div className="row">
        {running ? (
          <button onClick={onCancel}>{t("common.cancelBenchmark")}</button>
        ) : (
          <button onClick={onRun} disabled={!canRun}>
            {t("common.runBenchmark")}
          </button>
        )}
        <span style={{ color: "var(--anode)", fontSize: 12 }}>{label}</span>
      </div>
      <MetricsBanks
        promptTps={progress?.promptTps ?? null}
        decodeTps={progress?.decodeTps ?? null}
        agenticTps={progress?.agenticTps ?? null}
      />
      {lines.length > 0 && (
        <div className="dl-console">
          <div className="dl-console-head">$ {currentCommand}</div>
          <div className="dl-console-body" ref={boxRef}>
            {lines.map((line, i) => (
              <div key={i}>{line || "\u00a0"}</div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
