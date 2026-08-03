export interface DownloadedModel {
  server_id: string;
  repo_id: string;
  status: string;
}

interface Props {
  models: DownloadedModel[];
  onRemove: (serverId: string, repoId: string) => void;
}

export function DownloadedSection({ models, onRemove }: Props) {
  const byServer = models.reduce<Record<string, string[]>>((acc, m) => {
    (acc[m.server_id] ??= []).push(m.repo_id);
    return acc;
  }, {});
  return (
    <section className="panel">
      <span className="panel-cap">DOWNLOADED</span>
      <div className="row" style={{ gap: 16 }}>
        {Object.entries(byServer).map(([server, repos]) => (
          <div key={server}>
            <b>{server}:</b> {repos.join(", ")}
            {repos.map((r) => (
              <button key={r} onClick={() => onRemove(server, r)}>remove</button>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
