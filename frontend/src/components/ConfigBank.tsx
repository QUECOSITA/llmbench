import type { ConfigFit } from "../api/client";

export interface ConfigRow {
  flags: Record<string, string>;
  serving_command: string;
  bench_command?: string[];
  bench_tool?: string;
  bench_flags?: string;
  fit?: ConfigFit | null;
}

interface Props {
  n: number;
  onNChange: (n: number) => void;
  onGenerate: (n: number) => void;
  configs: ConfigRow[];
  onEdit?: (index: number, command: string) => void;
  onEditFlags?: (index: number, flags: string) => void;
}

export function ConfigBank({ n, onNChange, onGenerate, configs, onEdit, onEditFlags }: Props) {
  return (
    <section className="panel">
      <span className="panel-cap">02 · CONFIG BANK · N = {n}</span>
      <div className="row">
        <label style={{ color: "var(--anode)", fontSize: 12 }}>N</label>
        <input
          type="number"
          min={1}
          max={10}
          value={n}
          onChange={(e) => onNChange(Number(e.target.value))}
          style={{ width: 80 }}
        />
        <button onClick={() => onGenerate(n)}>GENERATE</button>
      </div>
      {configs.map((cfg, i) => (
        <div className="config-row" key={i}>
          <span className="config-index">▸ {i + 1}</span>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
            <textarea
              value={cfg.serving_command}
              onChange={(e) => onEdit?.(i, e.target.value)}
              rows={2}
              style={{ fontFamily: "var(--font-mono)" }}
            />
            {cfg.bench_tool === "speed-bench" && (
              <>
                <label style={{ color: "var(--anode)", fontSize: 11, letterSpacing: 1 }}>
                  SPEED-BENCH FLAGS
                </label>
                <textarea
                  value={cfg.bench_flags ?? ""}
                  onChange={(e) => onEditFlags?.(i, e.target.value)}
                  rows={2}
                  style={{ fontFamily: "var(--font-mono)" }}
                />
              </>
            )}
          </div>
          {cfg.bench_tool === "speed-bench" && (
            <span
              style={{
                fontSize: 10,
                letterSpacing: 1,
                color: "var(--accent)",
                border: "1px solid var(--hairline)",
                padding: "2px 6px",
                whiteSpace: "nowrap",
              }}
            >
              SPEED-BENCH
            </span>
          )}
          {cfg.fit && <FitBadge fit={cfg.fit} />}
        </div>
      ))}
    </section>
  );
}

export function FitBadge({ fit }: { fit: ConfigFit }) {
  const cls =
    fit.stage === "gpu"
      ? "fit-ok"
      : fit.stage === "offload"
        ? "fit-warn"
        : fit.stage === "cpu"
          ? "fit-cpu"
          : "fit-no";
  return (
    <span className={`fit-badge ${cls}`}>
      {fit.label} · {fit.needed_gb} GB
    </span>
  );
}
