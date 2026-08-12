import { useTranslation } from "react-i18next";

interface HardwareInfo {
  arch?: string;
  ram_total_gb?: number;
  gpu_name?: string | null;
  gpu_vram_gb?: number;
}

export function HardwareBar({ hardware }: { hardware: HardwareInfo }) {
  const { t } = useTranslation();
  const gpu = hardware.gpu_name ?? t("hardware.noGpu");
  const vram = hardware.gpu_vram_gb ? t("hardware.gbVram", { gb: hardware.gpu_vram_gb }) : "";
  return (
    <span className="hardware-line">
      {gpu} · {vram} · {hardware.ram_total_gb ? t("hardware.gbRam", { gb: hardware.ram_total_gb.toFixed(0) }) : "—"} ·{" "}
      {hardware.arch ?? "—"}
    </span>
  );
}
