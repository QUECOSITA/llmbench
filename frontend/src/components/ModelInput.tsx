interface Props {
  value: string;
  onChange: (value: string) => void;
  onAnalyze: (value: string) => void;
}

export function ModelInput({ value, onChange, onAnalyze }: Props) {
  return (
    <div className="row">
      <input
        placeholder="huggingface.co/Org/model"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ flex: 1 }}
      />
      <button onClick={() => onAnalyze(value.trim())}>ANALYZE</button>
    </div>
  );
}
