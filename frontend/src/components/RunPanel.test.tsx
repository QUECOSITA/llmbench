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
      waiting={false}
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={vi.fn()}
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
      waiting={false}
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={vi.fn()}
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
      waiting={false}
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={vi.fn()}
    />,
  );
  expect(screen.getByText("$ llama-bench -m x")).toBeInTheDocument();
  expect(screen.getByText(/loading\.\.\./)).toBeInTheDocument();
  expect(screen.getByText(/DECODE 80.0/)).toBeInTheDocument();
});

test("waiting shows the continue prompt and Enter triggers onContinue", () => {
  const onContinue = vi.fn();
  render(
    <RunPanel
      running
      onRun={vi.fn()}
      progress={{ index: 0, total: 1 }}
      lines={["▸ config 1/1 — $ bench"]}
      currentCommand="bench"
      waiting
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={onContinue}
    />,
  );
  expect(screen.getByText(/press enter to continue/i)).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Enter" });
  expect(onContinue).toHaveBeenCalledTimes(1);
});

test("CONTINUE button also triggers onContinue", () => {
  const onContinue = vi.fn();
  render(
    <RunPanel
      running
      onRun={vi.fn()}
      progress={null}
      lines={["x"]}
      currentCommand="bench"
      waiting
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={onContinue}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
  expect(onContinue).toHaveBeenCalledTimes(1);
});

test("PAUSE toggle is disabled while running and reflects its value", () => {
  const onPauseChange = vi.fn();
  const { rerender } = render(
    <RunPanel
      running
      onRun={vi.fn()}
      progress={null}
      lines={[]}
      currentCommand=""
      waiting={false}
      pause={true}
      onPauseChange={onPauseChange}
      onContinue={vi.fn()}
    />,
  );
  const checkbox = screen.getByRole("checkbox");
  expect(checkbox).toBeDisabled();
  expect(checkbox).toBeChecked();

  rerender(
    <RunPanel
      running={false}
      onRun={vi.fn()}
      progress={null}
      lines={[]}
      currentCommand=""
      waiting={false}
      pause={false}
      onPauseChange={onPauseChange}
      onContinue={vi.fn()}
    />,
  );
  const enabled = screen.getByRole("checkbox");
  expect(enabled).toBeEnabled();
  expect(enabled).not.toBeChecked();
});

test("console is hidden when there are no lines", () => {
  render(
    <RunPanel
      running={false}
      onRun={vi.fn()}
      progress={null}
      lines={[]}
      currentCommand=""
      waiting={false}
      pause={true}
      onPauseChange={vi.fn()}
      onContinue={vi.fn()}
    />,
  );
  expect(document.querySelector(".dl-console")).toBeNull();
});
