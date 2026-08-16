import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { ParseKeys } from "i18next";
import { api, FitVerdict, RunDetail } from "./api/client";
import type { ApiErrorContext, SpeedBenchInfo } from "./api/client";
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
import { LocaleSwitcher } from "./i18n/LocaleSwitcher";
import { statusLabel } from "./i18n/status";
import {
  downloadReducer,
  DownloadState,
} from "./ws/downloadReducer";
import "./styles/app.css";

interface Analysis {
  repo_id?: string;
  detected_server?: string | null;
  readme_has_serving_command?: boolean;
  readme_flags?: Record<string, string>;
  readme_flags_by_server?: Record<string, Record<string, string>>;
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
  const { t } = useTranslation();
  const vram = hardware?.gpu_vram_gb ?? 0;
  const ram = hardware?.ram_total_gb ?? 0;
  const colorMap: Record<string, string> = {
    gpu: "var(--ok)",
    ram_offload: "var(--warn)",
    ram: "var(--anode)",
    no_fit: "var(--accent)",
  };
  const fitKeyMap: Record<string, ParseKeys> = {
    gpu: "fit.gpu",
    ram_offload: "fit.ramOffload",
    ram: "fit.ram",
    no_fit: "fit.noFit",
  };
  const stage = fitKeyMap[verdict.stage] ? verdict.stage : "no_fit";
  return (
    <p style={{ color: colorMap[stage], fontSize: 12, margin: "4px 0 0" }}>
      {t(fitKeyMap[stage], { needed: verdict.needed_gb, vram, ram })}
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

function ErrorContextLine({ context }: { context: ApiErrorContext }) {
  const parts: string[] = [];
  if (context.active_run?.id != null) {
    parts.push(
      `run #${context.active_run.id} · ${context.active_run.repo_id ?? "?"} · ${context.active_run.status ?? "?"}`,
    );
  } else if (context.active_run_id != null) {
    parts.push(`run #${context.active_run_id}`);
  }
  if (context.config_index != null) {
    parts.push(`config #${context.config_index}${context.server_id ? ` · ${context.server_id}` : ""}`);
  }
  if (parts.length === 0) return null;
  return (
    <p style={{ color: "var(--anode)", fontSize: 12, opacity: 0.75, marginTop: 2 }}>
      {parts.join(" · ")}
    </p>
  );
}

export function App() {
  const { t } = useTranslation();
  const [hardware, setHardware] = useState<Record<string, unknown>>({});
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [server, setServer] = useState<string>("");
  const [n, setN] = useState(1);
  const [configs, setConfigs] = useState<ConfigRow[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorContext, setErrorContext] = useState<ApiErrorContext | null>(null);
  const [watchingRunId, setWatchingRunId] = useState<number | null>(null);
  const [modelInput, setModelInput] = useState("");
  const [downloaded, setDownloaded] = useState<
    Array<{ server_id: string; repo_id: string; status: string; gguf_filename?: string | null }>
  >([]);

  const [downloads, setDownloads] = useState<DownloadState>({});
  const [downloadKey, setDownloadKey] = useState<string | null>(null);
  const [confirmUnsupportedDownload, setConfirmUnsupportedDownload] = useState(false);
  const [dismissedUnsupported, setDismissedUnsupported] = useState(false);
  const [speedBenchInfo, setSpeedBenchInfo] = useState<SpeedBenchInfo | null>(null);
  const downloadEvents = useDownloadProgress();

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
    api.getSpeedBenchInfo().then(setSpeedBenchInfo).catch(() => {});
  }, []);

  const onAnalyze = useCallback(async (input: string) => {
    const data = await api.analyze(input);
    setAnalysis(data);
    setServer(data.detected_server ?? "");
    setConfigs([]);
    setDownloads({});
    setDownloadKey(null);
    setConfirmUnsupportedDownload(false);
    setDismissedUnsupported(false);
  }, []);

  const onLoad = useCallback(
    (repoId: string) => {
      setModelInput(repoId);
      void onAnalyze(repoId);
    },
    [onAnalyze],
  );

  const onGenerate = useCallback(async (count: number) => {
    if (!analysis?.repo_id) return;
    const effectiveServer = server || analysis.detected_server;
    if (!effectiveServer) {
      setError(t("model.noServerForGenerate"));
      return;
    }
    const data = await api.generateConfigs({
      repo_id: analysis.repo_id,
      server_id: effectiveServer,
      n: count,
      vram_gb: (hardware.gpu_vram_gb as number) ?? 0,
      readme_flags:
        analysis.readme_flags_by_server?.[effectiveServer] ?? analysis.readme_flags ?? {},
      weights_bytes: analysis.weights_bytes,
      ram_gb: (hardware.ram_total_gb as number) ?? 0,
      model_arch: analysis.model_arch,
    });
    setConfigs(data.configs);
  }, [analysis, hardware, server]);

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
        if (status && status !== "completed" && status !== "aborted" && status !== "cancelled") {
          setError(t("run.statusError", { status: statusLabel(status) }));
        }
      } catch {
        pollTimerRef.current = window.setTimeout(tick, 1000);
      }
    };
    pollTimerRef.current = window.setTimeout(tick, 1000);
  }, []);

  const watchRun = useCallback((runId: number) => {
    let stopped = false;
    const tick = async () => {
      if (stopped) return;
      try {
        const detail = await api.getRun(runId);
        if (stopped) return;
        const status = detail.status;
        const active = status === "running" || status === "queued";
        dispatch({
          type: "run_watch",
          run_id: runId,
          status,
          total: detail.total,
          results: (detail.results ?? []).map(toResultRow),
        });
        if (active) {
          pollTimerRef.current = window.setTimeout(tick, 1000);
          return;
        }
        setRunning(false);
        setWatchingRunId(null);
        if (status && status !== "completed" && status !== "aborted" && status !== "cancelled") {
          setError(t("run.statusError", { status: statusLabel(status) }));
        }
      } catch {
        pollTimerRef.current = window.setTimeout(tick, 1000);
      }
    };
    pollTimerRef.current = window.setTimeout(tick, 1000);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .listRuns()
      .then(({ runs }) => {
        if (cancelled) return;
        const active = runs.find((r) => r.status === "running" || r.status === "queued");
        if (active) {
          setWatchingRunId(active.id);
          dispatch({ type: "run_started", run_id: active.id, total: active.requested_n ?? 0 });
          if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current);
          watchRun(active.id);
          return;
        }
        const latest = runs.find((r) => r.status !== "running" && r.status !== "queued");
        if (!latest) return;
        return api.getRun(latest.id).then((detail) => {
          if (cancelled) return;
          dispatch({ type: "run_started", run_id: latest.id, total: latest.requested_n ?? 0 });
          dispatch({
            type: "run_sync",
            run_id: latest.id,
            status: detail.status ?? latest.status,
            total: detail.total ?? latest.requested_n ?? 0,
            results: (detail.results ?? []).map(toResultRow),
          });
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [watchRun]);

  useEffect(() => () => {
    if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current);
  }, []);

  const onRun = useCallback(async () => {
    if (!analysis?.repo_id || configs.length === 0) return;
    const effectiveServer = server || analysis.detected_server;
    if (!effectiveServer) return;
    setError(null);
    setErrorContext(null);
    setRunning(true);
    try {
      const { run_id } = await api.startBenchmark({
        repo_id: analysis.repo_id,
        configs: configs.map((c) => ({
          server_id: effectiveServer,
          flags: c.flags,
          serving_command: c.serving_command,
          bench_command: c.bench_command,
          bench_tool: c.bench_tool,
          bench_flags: c.bench_flags,
        })),
      });
      dispatch({ type: "run_started", run_id, total: configs.length });
      if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current);
      pollRun(run_id);
    } catch (err) {
      const apiErr = err as { status?: number; context?: ApiErrorContext };
      const activeRun = apiErr.context?.active_run;
      if (apiErr.status === 409 && activeRun?.id) {
        setWatchingRunId(activeRun.id);
        dispatch({
          type: "run_started",
          run_id: activeRun.id,
          total: activeRun.requested_n ?? 0,
        });
        if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current);
        watchRun(activeRun.id);
        return;
      }
      setRunning(false);
      setError(err instanceof Error ? err.message : String(err));
      if (apiErr.context && Object.keys(apiErr.context).length > 0) {
        setErrorContext(apiErr.context);
      }
    }
  }, [analysis, configs, pollRun, server, watchRun]);

  const onCancelRun = useCallback(async () => {
    setError(null);
    setErrorContext(null);
    try {
      await api.cancelBenchmark();
    } catch (err) {
      const apiErr = err as { status?: number };
      if (apiErr.status === 409) return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const events = useBenchmarkProgress();

  const processedEventsRef = useRef(0);
  useEffect(() => {
    for (let i = processedEventsRef.current; i < events.length; i++) {
      const ev = events[i];
      dispatch(ev);
      if (ev.type === "run_done") {
        setRunning(false);
        setWatchingRunId(null);
      }
    }
    processedEventsRef.current = events.length;
  }, [events]);

  const hasServingCommand = analysis?.readme_has_serving_command ?? true;
  const hasGguf = (analysis?.gguf_files?.length ?? 0) > 0;
  const noFit = analysis?.fit_verdict?.stage === "no_fit";
  const alreadyDownloaded = Boolean(analysis?.downloaded?.["llama.cpp"]);
  const effectiveServer = server || analysis?.detected_server;
  const downloadKeyForModel = effectiveServer && analysis?.repo_id ? `${effectiveServer}::${analysis.repo_id}` : null;
  const modelDownloaded = Boolean(
    effectiveServer &&
      (analysis?.downloaded?.[effectiveServer] || downloads[downloadKeyForModel ?? ""]?.status === "downloaded"),
  );

  return (
    <div className="instrument">
      <header className="instrument-header">
        <Link to="/" className="wordmark" style={{ textDecoration: "none", color: "var(--tube)" }}>
          LLM&nbsp;BENCH
        </Link>
        <HardwareBar hardware={hardware} />
        <LocaleSwitcher />
        <Link to="/results" className="nav-link">{t("nav.results")}</Link>
      </header>

      <Routes>
        <Route
          path="/"
          element={
            <main>
              <section className="panel">
                <span className="panel-cap">{t("panel.modelInput")}</span>
                <ModelInput value={modelInput} onChange={setModelInput} onAnalyze={onAnalyze} />
                {analysis?.repo_id && (
                  <p style={{ color: "var(--anode)", fontSize: 12, marginBottom: 4 }}>
                    {t("model.analysisSummary", {
                      repo: analysis.repo_id,
                      server: server || analysis.detected_server || t("model.serverManual"),
                      count: Object.keys(
                        (server && analysis.readme_flags_by_server?.[server]) || analysis.readme_flags || {},
                      ).length,
                    })}
                  </p>
                )}
                {analysis?.repo_id && analysis.detected_server && (
                  <div className="row" style={{ gap: 12, marginTop: 4, flexWrap: "wrap" }}>
                    <label style={{ color: "var(--anode)", fontSize: 12 }}>
                      {t("model.servingServer")}
                      <select
                        aria-label="serving server"
                        value={server || analysis.detected_server}
                        onChange={(e) => setServer(e.target.value)}
                        style={{ marginLeft: 6 }}
                      >
                        <option value={analysis.detected_server}>{analysis.detected_server}</option>
                      </select>
                    </label>
                  </div>
                )}
                {analysis?.repo_id && !analysis.detected_server && (
                  <p style={{ color: "var(--accent)", fontSize: 12, margin: "4px 0 0" }}>
                    {t("model.noServerProposed")}
                  </p>
                )}
                {analysis?.fit_verdict && (
                  <FitStatusLine verdict={analysis.fit_verdict} hardware={analysis.hardware} />
                )}
                {analysis?.repo_id && analysis.detected_server && (
                  <>
                    {!hasServingCommand ? (
                      <div className="row" style={{ gap: 12, marginTop: 4, flexWrap: "wrap", alignItems: "center" }}>
                        <p style={{ color: "var(--accent)", fontSize: 12, margin: 0 }}>
                          {hasGguf
                            ? t("model.noServingCommandWithGguf")
                            : t("model.noServingCommand")}
                        </p>
                        {hasGguf && !alreadyDownloaded && !confirmUnsupportedDownload && !dismissedUnsupported && (
                          <>
                            <button onClick={() => setConfirmUnsupportedDownload(true)}>{t("download.yesAnyway")}</button>
                            <button onClick={() => setDismissedUnsupported(true)}>{t("common.no")}</button>
                          </>
                        )}
                      </div>
                    ) : noFit ? (
                      <div className="row" style={{ gap: 12, marginTop: 4, flexWrap: "wrap", alignItems: "center" }}>
                        <p style={{ color: "var(--accent)", fontSize: 12, margin: 0 }}>
                          {t("fit.noFitNotice")}
                        </p>
                      </div>
                    ) : null}
                    {(hasServingCommand || confirmUnsupportedDownload || alreadyDownloaded) && (
                      <div className="row" style={{ gap: 12, marginTop: 8, flexWrap: "wrap" }}>
                        {[analysis.detected_server].map((sid) => {
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
                                  {dl.status === "downloading" ? t("dlStatus.downloading") : t("dlStatus.cancelled")}
                                </span>
                              ) : dl?.status === "error" ? (
                                <span style={{ color: "var(--accent)" }}>{t("download.error", { message: dl.message })}</span>
                              ) : done ? (
                                <span style={{ color: "var(--anode)" }}>{t("dlStatus.downloaded")}</span>
                              ) : (
                                <button onClick={() => onDownload(sid)}>{t("common.download")}</button>
                              )}
                            </span>
                          );
                        })}
                      </div>
                    )}
                  </>
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
                canGenerate={modelDownloaded}
                configs={configs}
                onEdit={(i, cmd) =>
                  setConfigs((prev) => prev.map((c, j) => (j === i ? { ...c, serving_command: cmd } : c)))
                }
                onEditFlags={(i, flags) =>
                  setConfigs((prev) => prev.map((c, j) => (j === i ? { ...c, bench_flags: flags } : c)))
                }
                speedBenchInfo={speedBenchInfo}
              />

              <RunPanel
                running={running}
                canRun={Boolean(analysis?.repo_id) && configs.length > 0 && Boolean(server || analysis?.detected_server)}
                onRun={onRun}
                onCancel={onCancelRun}
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
              />
              {watchingRunId !== null && (
                <p style={{ color: "var(--anode)", fontSize: 12 }}>
                  {t("run.watching", { id: watchingRunId })}
                </p>
              )}
              {error && <p style={{ color: "var(--accent)", fontSize: 12 }}>{t("common.error", { message: error })}</p>}
              {errorContext && <ErrorContextLine context={errorContext} />}

              <section className="panel">
                <div className="row">
                  <span className="panel-cap" style={{ marginBottom: 0 }}>{t("panel.resultsRanked")}</span>
                  {progressState.results.length > 0 && (
                    <button
                      className="btn-neutral"
                      onClick={() => dispatch({ type: "results_clear" })}
                      disabled={progressState.running}
                    >
                      {t("common.clear")}
                    </button>
                  )}
                </div>
                <ResultsTable rows={progressState.results} />
                <Link to="/results" className="results-link" style={{ fontSize: 12 }}>
                  {t("results.viewAll")}
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
