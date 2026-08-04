import { useEffect, useRef, useState } from "react";
import type { DownloadStatus } from "../ws/downloadReducer";

interface Props {
  status: DownloadStatus;
  onCancel: () => void;
  onPruneAnswer: (answer: "y" | "n") => void;
}

export function DownloadConsole({ status, onCancel, onPruneAnswer }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [answer, setAnswer] = useState("");

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [status.lines]);

  const submit = () => {
    const v = answer.trim().toLowerCase();
    if (v === "y" || v === "n") {
      onPruneAnswer(v);
      setAnswer("");
    }
  };

  return (
    <div className="dl-console">
      <div className="dl-console-head">$ {status.command}</div>
      <div className="dl-console-body" ref={boxRef}>
        {status.lines.map((line, i) => (
          <div key={i}>{line || "\u00a0"}</div>
        ))}
      </div>
      <div className="dl-console-actions">
        {status.status === "downloading" && (
          <button className="btn-neutral" onClick={onCancel}>CANCEL</button>
        )}
        {status.waitingInput && (
          <span style={{ color: "var(--anode)", fontSize: 12 }}>
            hf cache prune — Proceed? [y/N]
          </span>
        )}
        {status.waitingInput && (
          <input
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
            placeholder="y / n"
            style={{ width: 90 }}
          />
        )}
        {status.waitingInput && (
          <button onClick={() => onPruneAnswer("y")}>y</button>
        )}
        {status.waitingInput && (
          <button onClick={() => onPruneAnswer("n")}>n</button>
        )}
      </div>
      {status.status === "downloaded" && status.local_path && (
        <div style={{ color: "var(--ok)", fontSize: 12 }}>
          downloaded → {status.local_path}
        </div>
      )}
      {status.status === "pruned" && (
        <div style={{ color: "var(--anode)", fontSize: 12 }}>
          {status.pruneAccepted
            ? "cache pruned — retry the download when ready"
            : "prune skipped — retry the download when ready"}
        </div>
      )}
      {status.status === "error" && (
        <div style={{ color: "var(--accent)", fontSize: 12 }}>error: {status.message}</div>
      )}
    </div>
  );
}
