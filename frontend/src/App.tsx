import { useCallback, useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import { useBenchmarkProgress } from "./ws/useBenchmarkProgress";
import { ConfigBank, ConfigRow } from "./components/ConfigBank";
import { DownloadedSection } from "./components/DownloadedSection";
import { HardwareBar } from "./components/HardwareBar";
import { ModelInput } from "./components/ModelInput";
import { ResultRow, ResultsTable } from "./components/ResultsTable";
import { RunPanel } from "./components/RunPanel";
import { Results } from "./pages/Results";
import "./styles/app.css";

interface Analysis {
  repo_id?: string;
  detected_server?: string | null;
  readme_flags?: Record<string, string>;
  gguf_files?: Array<{ path: string; size: number }>;
  weights_bytes?: number;
  downloaded?: Record<string, boolean>;
}

interface ProgressState {
  index: number;
  total: number;
  promptTps?: number | null;
  decodeTps?: number | null;
}

export function App() {
  const [hardware, setHardware] = useState<Record<string, unknown>>({});
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [n, setN] = useState(4);
  const [configs, setConfigs] = useState<ConfigRow[]>([]);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<ProgressState | null>(null);
  const [results, setResults] = useState<ResultRow[]>([]);
  const [downloaded, setDownloaded] = useState<Array<{ server_id: string; repo_id: string; status: string }>>([]);

  useEffect(() => {
    api.getServers().then((d) => setHardware(d.hardware));
    api.listModels().then((d) => setDownloaded(d.models as never[]));
  }, []);

  const onAnalyze = useCallback(async (input: string) => {
    const data = (await api.analyze(input)) as Analysis;
    setAnalysis(data);
    setConfigs([]);
    setResults([]);
  }, []);

  const onGenerate = useCallback(async (count: number) => {
    if (!analysis?.repo_id || !analysis.detected_server) return;
    const data = await api.generateConfigs({
      repo_id: analysis.repo_id,
      server_id: analysis.detected_server,
      n: count,
      vram_gb: (hardware.gpu_vram_gb as number) ?? 0,
      readme_flags: analysis.readme_flags,
    });
    setConfigs(data.configs);
    setResults([]);
  }, [analysis, hardware]);

  const onRun = useCallback(async () => {
    if (!analysis?.repo_id || configs.length === 0) return;
    setResults([]);
    setRunning(true);
    setProgress({ index: 0, total: configs.length });
    await api.startBenchmark({
      repo_id: analysis.repo_id,
      configs: configs.map((c) => ({
        server_id: analysis.detected_server,
        flags: c.flags,
        serving_command: c.serving_command,
        bench_command: c.bench_command,
      })),
    });
  }, [analysis, configs]);

  const events = useBenchmarkProgress(running);

  useEffect(() => {
    for (const ev of events) {
      if (ev.type === "run_started") {
        setRunning(true);
        setProgress({ index: 0, total: ev.total ?? configs.length });
        setResults([]);
      } else if (ev.type === "config_done") {
        const idx = ev.index ?? 0;
        setProgress({
          index: idx,
          total: ev.total ?? configs.length,
          promptTps: ev.result?.prompt_processing_tps ?? null,
          decodeTps: ev.result?.decode_tps ?? null,
        });
        setResults((prev) => {
          const next = [...prev];
          next[idx] = {
            server_id: analysis?.detected_server ?? "",
            flag_conf: configs[idx]?.flags ?? {},
            prompt_processing_tps: ev.result?.prompt_processing_tps ?? null,
            decode_tps: ev.result?.decode_tps ?? null,
          };
          return next;
        });
      } else if (ev.type === "run_done") {
        setRunning(false);
      }
    }
  }, [events, analysis, configs]);

  return (
    <div className="instrument">
      <header className="instrument-header">
        <Link to="/" className="wordmark" style={{ textDecoration: "none", color: "var(--tube)" }}>
          LLM&nbsp;BENCH
        </Link>
        <HardwareBar hardware={hardware} />
        <Link to="/results" className="nav-link">RESULTS</Link>
      </header>

      <Routes>
        <Route
          path="/"
          element={
            <main>
              <section className="panel">
                <span className="panel-cap">01 · MODEL INPUT</span>
                <ModelInput onAnalyze={onAnalyze} />
                {analysis?.repo_id && (
                  <p style={{ color: "var(--anode)", fontSize: 12 }}>
                    → {analysis.repo_id} · server {analysis.detected_server ?? "manual"} ·{" "}
                    {Object.keys(analysis.readme_flags ?? {}).length} flags
                  </p>
                )}
              </section>

              <ConfigBank
                n={n}
                onNChange={setN}
                onGenerate={onGenerate}
                configs={configs}
                onEdit={(i, cmd) =>
                  setConfigs((prev) => prev.map((c, j) => (j === i ? { ...c, serving_command: cmd } : c)))
                }
              />

              <RunPanel
                running={running}
                canRun={Boolean(analysis?.repo_id) && configs.length > 0}
                onRun={onRun}
                progress={progress}
              />

              <section className="panel">
                <span className="panel-cap">05 · RESULTS — RANKED</span>
                <ResultsTable rows={results} />
                <Link to="/results" className="results-link" style={{ fontSize: 12 }}>
                  view all runs →
                </Link>
              </section>

              <DownloadedSection models={downloaded} onRemove={async (s, r) => {
                await api.removeModel(s, r);
                setDownloaded((await api.listModels()).models as never[]);
              }} />
            </main>
          }
        />
        <Route path="/results" element={<Results />} />
      </Routes>
    </div>
  );
}
