interface Props {
  promptTps: number | null;
  decodeTps: number | null;
  best?: boolean;
}

export function MetricsBanks({ promptTps, decodeTps, best }: Props) {
  return (
    <div className="metrics">
      <div className="bank">
        <span className="panel-cap">PROMPT PROC · t/s</span>
        <div className="digit">{promptTps?.toFixed(1) ?? "—"}</div>
      </div>
      <div className="bank">
        <span className="panel-cap">DECODE STAGE · t/s</span>
        <div className={`digit ${best ? "digit-best" : ""}`}>{decodeTps?.toFixed(1) ?? "—"}</div>
      </div>
    </div>
  );
}
