import { fireEvent, render, screen } from "@testing-library/react";
import { RunPanel } from "./RunPanel";

test("run button disabled while running", () => {
  render(
    <RunPanel
      running
      onRun={vi.fn()}
      progress={{ index: 0, total: 4 }}
      lines={[]}
      currentCommand=""
    />,
  );
  expect(screen.getByText(/run benchmark/i)).toBeDisabled();
  expect(screen.getByText(/1\/4/i)).toBeInTheDocument();
});

test("run button triggers onRun", () => {
  const onRun = vi.fn();
  render(
    <RunPanel
      running={false}
      onRun={onRun}
      progress={null}
      lines={[]}
      currentCommand=""
    />,
  );
  fireEvent.click(screen.getByText(/run benchmark/i));
  expect(onRun).toHaveBeenCalled();
});

test("console renders accumulated lines and the current command", () => {
  render(
    <RunPanel
      running={false}
      onRun={vi.fn()}
      progress={{ index: 0, total: 2 }}
      lines={["▸ config 1/2 — $ llama-bench -m x", "loading...", "PROMPT 100.0 · DECODE 80.0 · ok"]}
      currentCommand="llama-bench -m x"
    />,
  );
  expect(screen.getByText("$ llama-bench -m x")).toBeInTheDocument();
  expect(screen.getByText(/loading\.\.\./)).toBeInTheDocument();
  expect(screen.getByText(/DECODE 80.0/)).toBeInTheDocument();
});

test("console is hidden when there are no lines", () => {
  render(
    <RunPanel
      running={false}
      onRun={vi.fn()}
      progress={null}
      lines={[]}
      currentCommand=""
    />,
  );
  expect(document.querySelector(".dl-console")).toBeNull();
});
