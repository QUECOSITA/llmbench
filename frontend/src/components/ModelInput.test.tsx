import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ModelInput } from "./ModelInput";

test("calls onAnalyze with trimmed value", () => {
  const onAnalyze = vi.fn();
  function Harness() {
    const [value, setValue] = useState(" https://huggingface.co/org/model ");
    return <ModelInput value={value} onChange={setValue} onAnalyze={onAnalyze} />;
  }
  render(<Harness />);
  fireEvent.click(screen.getByText(/analyze/i));
  expect(onAnalyze).toHaveBeenCalledWith("https://huggingface.co/org/model");
});
