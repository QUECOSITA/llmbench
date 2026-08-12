import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, RunSummary } from "../api/client";
import { statusLabel } from "../i18n/status";

export function Results({ initialRuns }: { initialRuns?: RunSummary[] }) {
  const { t } = useTranslation();
  const [runs, setRuns] = useState<RunSummary[] | null>(initialRuns ?? null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (runs === null) {
      api.listRuns().then((d) => setRuns(d.runs)).catch(() => setRuns([]));
    }
  }, [runs]);

  const runActive = runs?.some((r) => r.status === "running" || r.status === "queued") ?? false;

  const onClear = async () => {
    if (!window.confirm(t("confirm.clearHistory"))) return;
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
        <span className="panel-cap" style={{ marginBottom: 0 }}>{t("panel.resultsAllRuns")}</span>
        {runs && runs.length > 0 && (
          <button className="btn-neutral" onClick={onClear} disabled={runActive}>
            {t("common.clearHistory")}
          </button>
        )}
      </div>
      <p style={{ color: "var(--anode)", fontSize: 12 }}>
        <Link to="/" className="results-link">{t("results.backToBench")}</Link>
      </p>
      {error && <p style={{ color: "var(--accent)", fontSize: 12 }}>{t("common.error", { message: error })}</p>}
      {!runs || runs.length === 0 ? (
        <p style={{ color: "var(--anode)" }}>{t("results.empty")}</p>
      ) : (
        <ul>
          {runs.map((r) => (
            <li key={r.id}>
              {t("results.runLine", {
                id: r.id,
                repo: r.repo_id,
                n: r.requested_n,
                status: statusLabel(r.status),
              })}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
