import { fireEvent, render, screen } from "@testing-library/react";
import { ModelInput } from "./ModelInput";

test("calls onAnalyze with trimmed value", () => {
  const onAnalyze = vi.fn();
  render(<ModelInput onAnalyze={onAnalyze} />);
  fireEvent.change(screen.getByPlaceholderText(/huggingface/i), {
    target: { value: " https://huggingface.co/org/model " },
  });
  fireEvent.click(screen.getByText(/analyze/i));
  expect(onAnalyze).toHaveBeenCalledWith("https://huggingface.co/org/model");
});
