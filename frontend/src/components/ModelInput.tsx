import { useTranslation } from "react-i18next";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onAnalyze: (value: string) => void;
}

export function ModelInput({ value, onChange, onAnalyze }: Props) {
  const { t } = useTranslation();
  return (
    <div className="row">
      <input
        placeholder="huggingface.co/Org/model"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ flex: 1 }}
      />
      <button onClick={() => onAnalyze(value.trim())}>{t("common.analyze")}</button>
    </div>
  );
}
