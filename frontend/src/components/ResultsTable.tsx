export interface ResultRow {
  server_id: string;
  flag_conf: Record<string, string>;
  prompt_processing_tps: number | null;
  decode_tps: number | null;
}

export function ResultsTable({ rows }: { rows: ResultRow[] }) {
  const sorted = [...rows].sort((a, b) => (b.decode_tps ?? -1) - (a.decode_tps ?? -1));
  const flagNames = [...new Set(sorted.flatMap((r) => Object.keys(r.flag_conf)))];
  return (
    <table className="results-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Program</th>
          {flagNames.map((f) => <th key={f}>{f}</th>)}
          <th>PROMPT t/s</th>
          <th>DECODE t/s</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r, i) => (
          <tr key={i} className={i === 0 ? "row-best" : ""}>
            <td>{i + 1}</td>
            <td>{r.server_id}</td>
            {flagNames.map((f) => <td key={f}>{r.flag_conf[f] ?? "—"}</td>)}
            <td>{r.prompt_processing_tps?.toFixed(1) ?? "—"}</td>
            <td className={i === 0 ? "digit-best" : ""}>{r.decode_tps?.toFixed(1) ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
