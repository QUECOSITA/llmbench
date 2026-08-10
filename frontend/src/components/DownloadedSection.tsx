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

const SERVER_ORDER = ["llama.cpp"];

export function DownloadedSection({ models, onLoad, onRemove }: Props) {
  const byRepo = new Map<string, string[]>();
  const ggufByRepo = new Map<string, string>();
  for (const m of models) {
    if (m.status !== "downloaded") continue;
    const servers = byRepo.get(m.repo_id) ?? [];
    if (!servers.includes(m.server_id)) servers.push(m.server_id);
    byRepo.set(m.repo_id, servers);
    if (m.gguf_filename) ggufByRepo.set(m.repo_id, m.gguf_filename);
  }
  const repos = [...byRepo.keys()].sort();

  return (
    <section className="panel">
      <span className="panel-cap">DOWNLOADED</span>
      {repos.length === 0 && <p className="downloaded-empty">no models downloaded</p>}
      {repos.map((repo) => {
        const group = byRepo.get(repo)!;
        const servers = [
          ...SERVER_ORDER.filter((s) => group.includes(s)),
          ...group.filter((s) => !SERVER_ORDER.includes(s)),
        ];
        const gguf = ggufByRepo.get(repo);
        const modelRef = gguf ? `${repo}/${gguf}` : repo;
        return (
          <div key={repo} className="downloaded-row">
            <span className="downloaded-server">
              {servers.map((s) => SERVER_DISPLAY[s] ?? s).join(", ")}
            </span>
            <span className="downloaded-model">{modelRef}</span>
            <span className="downloaded-actions">
              <button className="btn-neutral" onClick={() => onLoad(modelRef)}>
                LOAD
              </button>
              <button
                className="btn-neutral"
                onClick={() => {
                  if (window.confirm(`Remove ${modelRef} from the HF cache?`)) {
                    onRemove(repo);
                  }
                }}
              >
                REMOVE
              </button>
            </span>
          </div>
        );
      })}
    </section>
  );
}
