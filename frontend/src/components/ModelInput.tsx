import { useState } from "react";

export function ModelInput({ onAnalyze }: { onAnalyze: (value: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="row">
      <input
        placeholder="huggingface.co/Org/model"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        style={{ flex: 1 }}
      />
      <button onClick={() => onAnalyze(value.trim())}>ANALYZE</button>
    </div>
  );
}
