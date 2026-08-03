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
}

export function RunPanel({ running, onRun, progress, canRun = true }: Props) {
  const label = progress ? `config ${progress.index + 1}/${progress.total}` : "";
  return (
    <section className="panel">
      <span className="panel-cap">03 · RUN</span>
      <div className="row">
        <button onClick={onRun} disabled={running || !canRun}>
          RUN BENCHMARK
        </button>
        <span style={{ color: "var(--anode)", fontSize: 12 }}>{label}</span>
      </div>
      <MetricsBanks
        promptTps={progress?.promptTps ?? null}
        decodeTps={progress?.decodeTps ?? null}
      />
    </section>
  );
}
