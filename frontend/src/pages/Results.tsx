import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";

export interface RunSummary {
  id: number;
  repo_id: string;
  requested_n: number;
  created_at: string;
  status: string;
}

export function Results({ initialRuns }: { initialRuns?: RunSummary[] }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(initialRuns ?? null);

  useEffect(() => {
    if (runs === null) {
      api.listRuns().then((d) => setRuns(d.runs as RunSummary[])).catch(() => setRuns([]));
    }
  }, [runs]);

  return (
    <section className="panel">
      <span className="panel-cap">RESULTS · ALL RUNS</span>
      <p style={{ color: "var(--anode)", fontSize: 12 }}>
        <Link to="/" className="results-link">← back to bench</Link>
      </p>
      {!runs || runs.length === 0 ? (
        <p style={{ color: "var(--anode)" }}>No benchmark runs yet.</p>
      ) : (
        <ul>
          {runs.map((r) => (
            <li key={r.id}>
              #{r.id} · {r.repo_id} · {r.requested_n} configs · {r.status}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
