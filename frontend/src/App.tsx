import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { api, FitVerdict, RunDetail } from "./api/client";
import { INITIAL_STATE, progressReducer, ResultRow, useBenchmarkProgress } from "./ws/useBenchmarkProgress";
import { useDownloadProgress } from "./ws/useDownloadProgress";
import { ConfigBank, ConfigRow } from "./components/ConfigBank";
import { DownloadConsole } from "./components/DownloadConsole";
import { DownloadedSection } from "./components/DownloadedSection";
import { HardwareBar } from "./components/HardwareBar";
import { ModelInput } from "./components/ModelInput";
import { ResultsTable } from "./components/ResultsTable";
import { RunPanel } from "./components/RunPanel";
import { Results } from "./pages/Results";
import {
  downloadActive,
  downloadReducer,
  DownloadState,
} from "./ws/downloadReducer";
import "./styles/app.css";

const KNOWN_SERVERS = ["llama.cpp", "vllm", "sglang"] as const;

interface Analysis {
  repo_id?: string;
  detected_server?: string | null;
  readme_flags?: Record<string, string>;
  gguf_files?: Array<{ path: string; size: number }>;
  weights_bytes?: number;
  downloaded?: Record<string, boolean>;
  fit_verdict?: { stage: string; warning: boolean; needed_gb: number };
  model_arch?: { layers: number; heads: number; hidden: number; max_ctx: number };
  hardware?: { gpu_vram_gb?: number; ram_total_gb?: number; gpu_name?: string };
}

function FitStatusLine({
  verdict,
  hardware,
}: {
  verdict: FitVerdict;
  hardware?: Analysis["hardware"];
}) {
  const vram = hardware?.gpu_vram_gb ?? 0;
  const ram = hardware?.ram_total_gb ?? 0;
  const map: Record<string, { text: string; color: string }> = {
    gpu: {
      text: `FITS VRAM — needs ~${verdict.needed_gb} GB (weights + KV) of ${vram} GB VRAM`,
      color: "var(--ok)",
    },
    ram_offload: {
      text: `OFFLOADS TO RAM — needs ~${verdict.needed_gb} GB, spills past ${vram} GB VRAM into ${ram} GB RAM`,
      color: "var(--warn)",
    },
    ram: {
      text: `CPU ONLY — no GPU VRAM, needs ~${verdict.needed_gb} GB of ${ram} GB RAM`,
      color: "var(--anode)",
    },
    no_fit: {
      text: `NO FIT — needs ~${verdict.needed_gb} GB vs ${vram} GB VRAM + ${ram} GB RAM`,
      color: "var(--accent)",
    },
  };
  const entry = map[verdict.stage] ?? map.no_fit;
  return (
    <p style={{ color: entry.color, fontSize: 12, margin: "4px 0 0" }}>
      {entry.text}
    </p>
  );
}

function toResultRow(r: RunDetail["results"][number]): ResultRow {
  return {
    server_id: r.server_id ?? "",
    flag_conf: r.flag_conf ?? {},
    prompt_processing_tps: r.prompt_processing_tps ?? null,
    decode_tps: r.decode_tps ?? null,
    result_status: r.result_status ?? null,
  };
}

export function App() {
  const [hardware, setHardware] = useState<Record<string, unknown>>({});
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [n, setN] = useState(4);
  const [configs, setConfigs] = useState<ConfigRow[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modelInput, setModelInput] = useState("");
  const [pause, setPause] = useState(true);
  const [downloaded, setDownloaded] = useState<
    Array<{ server_id: string; repo_id: string; status: string; gguf_filename?: string | null }>
  >([]);

  const [downloads, setDownloads] = useState<DownloadState>({});
  const [downloadKey, setDownloadKey] = useState<string | null>(null);
  const downloadActiveNow = downloadActive(downloads);
  const downloadEvents = useDownloadProgress(downloadActiveNow);

  useEffect(() => {
    for (const ev of downloadEvents) {
      setDownloads((prev) => downloadReducer(prev, ev));
      if (ev.type === "download_done") {
        api.listModels().then((d) => setDownloaded(d.models));
      }
    }
  }, [downloadEvents]);

  const onDownload = useCallback(
    async (serverId: string) => {
      if (!analysis?.repo_id) return;
      const k = `${serverId}::${analysis.repo_id}`;
      setDownloadKey(k);
      setDownloads((prev) => ({
        ...prev,
        [k]: { status: "downloading", command: "", lines: [], waitingInput: false, pruneAccepted: null, progress: false },
      }));
      try {
        const gguf = analysis.gguf_files?.length === 1 ? analysis.gguf_files[0].path : undefined;
        await api.downloadModel({ repo_id: analysis.repo_id, server_id: serverId, gguf_filename: gguf });
      } catch (err) {
        setDownloads((prev) => ({
          ...prev,
          [k]: { ...prev[k], status: "error", message: err instanceof Error ? err.message : String(err) },
        }));
      }
    },
    [analysis],
  );

  const onCancel = useCallback(async () => {
    try {
      await api.cancelDownload();
    } catch (err) {
      if (!downloadKey) return;
      setDownloads((prev) => ({
        ...prev,
        [downloadKey]: {
          ...prev[downloadKey],
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        },
      }));
    }
  }, [downloadKey]);

  const onPruneAnswer = useCallback(
    async (answer: "y" | "n") => {
      try {
        await api.answerPrune(answer);
      } catch (err) {
        if (!downloadKey) return;
        setDownloads((prev) => ({
          ...prev,
          [downloadKey]: {
            ...prev[downloadKey],
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          },
        }));
      }
    },
    [downloadKey],
  );

  useEffect(() => {
    api.getServers().then((d) => setHardware(d.hardware));
    api.listModels().then((d) => setDownloaded(d.models));
  }, []);

  const onAnalyze = useCallback(async (input: string) => {
    const data = await api.analyze(input);
    setAnalysis(data);
    setConfigs([]);
    setDownloads({});
    setDownloadKey(null);
  }, []);

  const onLoad = useCallback(
    (repoId: string) => {
      setModelInput(repoId);
      void onAnalyze(repoId);
    },
    [onAnalyze],
  );

  const onGenerate = useCallback(async (count: number) => {
    if (!analysis?.repo_id || !analysis.detected_server) return;
    const data = await api.generateConfigs({
      repo_id: analysis.repo_id,
      server_id: analysis.detected_server,
      n: count,
      vram_gb: (hardware.gpu_vram_gb as number) ?? 0,
      readme_flags: analysis.readme_flags ?? {},
      weights_bytes: analysis.weights_bytes,
      ram_gb: (hardware.ram_total_gb as number) ?? 0,
      model_arch: analysis.model_arch,
    });
    setConfigs(data.configs);
  }, [analysis, hardware]);

  const [progressState, dispatch] = useReducer(progressReducer, INITIAL_STATE);

  const pollTimerRef = useRef<number | null>(null);
  const pollRun = useCallback((runId: number) => {
    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      try {
        const detail = await api.getRun(runId);
        if (stopped) return;
        const status = detail.status;
        const active = status === "running" || status === "queued";
        if (active) {
          pollTimerRef.current = window.setTimeout(tick, 1000);
          return;
        }
        dispatch({
          type: "run_sync",
          run_id: runId,
          status,
          total: detail.total,
          results: (detail.results ?? []).map(toResultRow),
        });
        setRunning(false);
        if (status && status !== "completed") {
          setError(`run ${status}`);
        }
      } catch {
        pollTimerRef.current = window.setTimeout(tick, 1000);
      }
    };
    pollTimerRef.current = window.setTimeout(tick, 1000);
  }, []);

  useEffect(() => () => {
    if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current);
  }, []);

  const onRun = useCallback(async () => {
    if (!analysis?.repo_id || configs.length === 0) return;
    setError(null);
    setRunning(true);
    try {
      const { run_id } = await api.startBenchmark({
        repo_id: analysis.repo_id,
        pause,
        configs: configs.map((c) => ({
          server_id: analysis.detected_server,
          flags: c.flags,
          serving_command: c.serving_command,
          bench_command: c.bench_command,
        })),
      });
      dispatch({ type: "run_started", run_id, total: configs.length });
      if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current);
      pollRun(run_id);
    } catch (err) {
      setRunning(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [analysis, configs, pause, pollRun]);

  const onContinue = useCallback(async () => {
    if (progressState.runId === null) return;
    try {
      await api.continueRun(progressState.runId);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.startsWith("409")) return;
      setError(message);
    }
  }, [progressState.runId]);

  const events = useBenchmarkProgress();

  const processedEventsRef = useRef(0);
  useEffect(() => {
    for (let i = processedEventsRef.current; i < events.length; i++) {
      const ev = events[i];
      dispatch(ev);
      if (ev.type === "run_done") setRunning(false);
    }
    processedEventsRef.current = events.length;
  }, [events]);

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
                <ModelInput value={modelInput} onChange={setModelInput} onAnalyze={onAnalyze} />
                {analysis?.repo_id && (
                  <p style={{ color: "var(--anode)", fontSize: 12, marginBottom: 4 }}>
                    → {analysis.repo_id} · server {analysis.detected_server ?? "manual"} ·{" "}
                    {Object.keys(analysis.readme_flags ?? {}).length} flags
                  </p>
                )}
                {analysis?.fit_verdict && (
                  <FitStatusLine verdict={analysis.fit_verdict} hardware={analysis.hardware} />
                )}
                {analysis?.repo_id && (
                  <div className="row" style={{ gap: 12, marginTop: 8, flexWrap: "wrap" }}>
                    {KNOWN_SERVERS.map((sid) => {
                      const k = `${sid}::${analysis.repo_id}`;
                      const dl = downloads[k];
                      const already = analysis.downloaded?.[sid];
                      const busy = dl && (dl.status === "downloading" || dl.status === "cancelled" || dl.status === "pruning");
                      const done = dl?.status === "downloaded" || already;
                      return (
                        <span key={sid} style={{ fontSize: 12 }}>
                          <b>{sid}:</b>{" "}
                          {busy ? (
                            <span style={{ color: "var(--anode)" }}>
                              {dl.status === "downloading" ? "downloading" : "cancelled"}
                            </span>
                          ) : dl?.status === "error" ? (
                            <span style={{ color: "var(--accent)" }}>error: {dl.message}</span>
                          ) : done ? (
                            <span style={{ color: "var(--anode)" }}>downloaded</span>
                          ) : (
                            <button onClick={() => onDownload(sid)}>Download</button>
                          )}
                        </span>
                      );
                    })}
                  </div>
                )}
                {downloadKey && downloads[downloadKey] && (
                  <DownloadConsole
                    status={downloads[downloadKey]}
                    onCancel={onCancel}
                    onPruneAnswer={onPruneAnswer}
                  />
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
                progress={
                  progressState.running || progressState.results.length > 0
                    ? {
                        index: progressState.index,
                        total: progressState.total,
                        promptTps: progressState.promptTps,
                        decodeTps: progressState.decodeTps,
                      }
                    : null
                }
                lines={progressState.lines}
                currentCommand={progressState.currentCommand}
                waiting={progressState.waiting}
                pause={pause}
                onPauseChange={setPause}
                onContinue={onContinue}
              />
              {error && <p style={{ color: "var(--accent)", fontSize: 12 }}>Error: {error}</p>}

              <section className="panel">
                <span className="panel-cap">05 · RESULTS — RANKED</span>
                <ResultsTable rows={progressState.results} />
                <Link to="/results" className="results-link" style={{ fontSize: 12 }}>
                  view all runs →
                </Link>
              </section>

              <DownloadedSection
                models={downloaded}
                onLoad={onLoad}
                onRemove={async (r) => {
                  await api.removeModel(r);
                  setDownloaded((await api.listModels()).models);
                }}
              />
            </main>
          }
        />
        <Route path="/results" element={<Results />} />
      </Routes>
    </div>
  );
}
