import { fireEvent, render, screen } from "@testing-library/react";
import { ConfigBank } from "./ConfigBank";

test("renders editable config rows and calls onGenerate with N", () => {
  const onGenerate = vi.fn();
  const configs = [
    { flags: { "--max-model-len": "8192" }, serving_command: "vllm serve m --max-model-len 8192" },
    { flags: { "--max-model-len": "4096" }, serving_command: "vllm serve m --max-model-len 4096" },
  ];
  render(<ConfigBank n={4} onNChange={() => {}} onGenerate={onGenerate} configs={configs} />);
  expect(screen.getByText(/vllm serve m --max-model-len 8192/i)).toBeInTheDocument();
  fireEvent.click(screen.getByText(/generate/i));
  expect(onGenerate).toHaveBeenCalledWith(4);
});

test("edits a serving command", () => {
  const onEdit = vi.fn();
  const configs = [{ flags: {}, serving_command: "vllm serve m" }];
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} onEdit={onEdit} />);
  const textarea = screen.getByDisplayValue("vllm serve m");
  fireEvent.change(textarea, { target: { value: "vllm serve m --max-model-len 16384" } });
  expect(onEdit).toHaveBeenCalled();
});
