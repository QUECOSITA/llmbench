interface HardwareInfo {
  arch?: string;
  ram_total_gb?: number;
  gpu_name?: string | null;
  gpu_vram_gb?: number;
}

export function HardwareBar({ hardware }: { hardware: HardwareInfo }) {
  const gpu = hardware.gpu_name ?? "no GPU";
  const vram = hardware.gpu_vram_gb ? `${hardware.gpu_vram_gb}GB VRAM` : "";
  return (
    <span className="hardware-line">
      {gpu} · {vram} · {hardware.ram_total_gb ? `${hardware.ram_total_gb.toFixed(0)}GB RAM` : "—"} ·{" "}
      {hardware.arch ?? "—"}
    </span>
  );
}
