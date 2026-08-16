import { useTranslation } from "react-i18next";

export interface DownloadedModel {
  server_id: string;
  repo_id: string;
  status: string;
  gguf_filename?: string | null;
}

interface Props {
  models: DownloadedModel[];
  onLoad: (repoId: string) => void;
  onRemove: (repoId: string) => void;
}

const SERVER_DISPLAY: Record<string, string> = {
  "llama.cpp": "llama.cpp",
};

export function DownloadedSection({ models, onLoad, onRemove }: Props) {
  const { t } = useTranslation();
  const rows = models
    .filter((m) => m.status === "downloaded")
    .map((m) => ({ ...m, ref: m.gguf_filename ? `${m.repo_id}/${m.gguf_filename}` : m.repo_id }))
    .sort((a, b) => a.ref.localeCompare(b.ref));

  return (
    <section className="panel">
      <span className="panel-cap">{t("panel.downloaded")}</span>
      {rows.length === 0 && <p className="downloaded-empty">{t("downloaded.empty")}</p>}
      {rows.map((row) => (
        <div key={row.ref} className="downloaded-row">
          <span className="downloaded-server">{SERVER_DISPLAY[row.server_id] ?? row.server_id}</span>
          <span className="downloaded-model">{row.ref}</span>
          <span className="downloaded-actions">
            <button className="btn-neutral" onClick={() => onLoad(row.ref)}>
              {t("common.load")}
            </button>
            <button
              className="btn-neutral"
              onClick={() => {
                if (window.confirm(t("confirm.removeModel", { model: row.ref }))) {
                  onRemove(row.repo_id);
                }
              }}
            >
              {t("common.remove")}
            </button>
          </span>
        </div>
      ))}
    </section>
  );
}
