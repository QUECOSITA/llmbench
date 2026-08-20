import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { DecisionModal } from "./DecisionModal";

const decision = {
  run_id: 1,
  index: 2,
  proposed_tool: "read_file",
  proposed_args: { path: "/repo/main.py" },
  tool_options: ["read_file", "search", "finish", "submit_plan"],
};

function argsTextarea(): HTMLTextAreaElement {
  return screen.getByRole("textbox") as HTMLTextAreaElement;
}

describe("DecisionModal", () => {
  test("pre-fills the proposed tool and args and submits on Continue", () => {
    const onSubmit = vi.fn();
    render(<DecisionModal decision={decision} onSubmit={onSubmit} onCancel={() => {}} />);
    expect(screen.getByDisplayValue("read_file")).toBeTruthy();
    expect(argsTextarea().value).toContain('"path": "/repo/main.py"');
    fireEvent.click(screen.getByText("CONTINUE"));
    expect(onSubmit).toHaveBeenCalledWith("read_file", { path: "/repo/main.py" });
  });

  test("allows changing the tool and editing args", () => {
    const onSubmit = vi.fn();
    render(<DecisionModal decision={decision} onSubmit={onSubmit} onCancel={() => {}} />);
    fireEvent.change(screen.getByDisplayValue("read_file"), { target: { value: "search" } });
    fireEvent.change(argsTextarea(), { target: { value: '{"query": "x"}' } });
    fireEvent.click(screen.getByText("CONTINUE"));
    expect(onSubmit).toHaveBeenCalledWith("search", { query: "x" });
  });

  test("rejects invalid JSON args", () => {
    const onSubmit = vi.fn();
    render(<DecisionModal decision={decision} onSubmit={onSubmit} onCancel={() => {}} />);
    fireEvent.change(argsTextarea(), { target: { value: "not json" } });
    fireEvent.click(screen.getByText("CONTINUE"));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("FINISH / CANCEL calls onCancel", () => {
    const onCancel = vi.fn();
    render(<DecisionModal decision={decision} onSubmit={() => {}} onCancel={onCancel} />);
    fireEvent.click(screen.getByText("FINISH / CANCEL"));
    expect(onCancel).toHaveBeenCalled();
  });
});
