import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, RunSummary } from "../api/client";

export function Results({ initialRuns }: { initialRuns?: RunSummary[] }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(initialRuns ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (runs === null) {
      api.listRuns().then((d) => setRuns(d.runs)).catch(() => setRuns([]));
    }
  }, [runs]);

  const runActive = runs?.some((r) => r.status === "running" || r.status === "queued") ?? false;

  const onClear = async () => {
    if (!window.confirm(
      "Clear all benchmark history? This removes every run and its raw speed-bench outputs. Downloaded models are kept.",
    )) return;
    setError(null);
    try {
      await api.clearRuns();
      setRuns([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <section className="panel">
      <div className="row">
        <span className="panel-cap" style={{ marginBottom: 0 }}>RESULTS · ALL RUNS</span>
        {runs && runs.length > 0 && (
          <button className="btn-neutral" onClick={onClear} disabled={runActive}>
            CLEAR HISTORY
          </button>
        )}
      </div>
      <p style={{ color: "var(--anode)", fontSize: 12 }}>
        <Link to="/" className="results-link">← back to bench</Link>
      </p>
      {error && <p style={{ color: "var(--accent)", fontSize: 12 }}>Error: {error}</p>}
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
