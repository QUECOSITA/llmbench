import { useTranslation } from "react-i18next";

interface Props {
  promptTps: number | null;
  decodeTps: number | null;
  agenticTps: number | null;
  best?: boolean;
}

export function MetricsBanks({ promptTps, decodeTps, agenticTps, best }: Props) {
  const { t } = useTranslation();
  const bestOnAgentic = agenticTps != null;
  return (
    <div className="metrics">
      <div className="bank">
        <span className="panel-cap">{t("metrics.promptProc")}</span>
        <div className="digit">{promptTps?.toFixed(1) ?? "—"}</div>
      </div>
      <div className="bank">
        <span className="panel-cap">{t("metrics.decodeStage")}</span>
        <div className={`digit ${best && !bestOnAgentic ? "digit-best" : ""}`}>{decodeTps?.toFixed(1) ?? "—"}</div>
      </div>
      <div className="bank">
        <span className="panel-cap">{t("metrics.agentic")}</span>
        <div className={`digit ${best && bestOnAgentic ? "digit-best" : ""}`}>{agenticTps?.toFixed(1) ?? "—"}</div>
      </div>
    </div>
  );
}
