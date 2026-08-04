import { fireEvent, render, screen } from "@testing-library/react";
import { DownloadConsole } from "./DownloadConsole";
import type { DownloadStatus } from "../ws/downloadReducer";

function status(over: Partial<DownloadStatus> = {}): DownloadStatus {
  return {
    status: "downloading",
    command: "hf download org/model",
    lines: ["Fetching..."],
    waitingInput: false,
    pruneAccepted: null,
    progress: false,
    ...over,
  };
}

test("renders command header and console lines, cancel calls onCancel", () => {
  const onCancel = vi.fn();
  const onPruneAnswer = vi.fn();
  render(<DownloadConsole status={status()} onCancel={onCancel} onPruneAnswer={onPruneAnswer} />);
  expect(screen.getByText(/\$ hf download org\/model/i)).toBeInTheDocument();
  expect(screen.getByText("Fetching...")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

test("no cancel button outside downloading", () => {
  render(
    <DownloadConsole
      status={status({ status: "pruning", command: "hf cache prune --format human" })}
      onCancel={vi.fn()}
      onPruneAnswer={vi.fn()}
    />,
  );
  expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
});

test("y/n prompt answers call onPruneAnswer", () => {
  const onPruneAnswer = vi.fn();
  render(
    <DownloadConsole
      status={status({ status: "pruning", command: "hf cache prune --format human", waitingInput: true })}
      onCancel={vi.fn()}
      onPruneAnswer={onPruneAnswer}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "y" }));
  expect(onPruneAnswer).toHaveBeenCalledWith("y");
  fireEvent.click(screen.getByRole("button", { name: "n" }));
  expect(onPruneAnswer).toHaveBeenCalledWith("n");
});

test("typed y/n submits on Enter", () => {
  const onPruneAnswer = vi.fn();
  render(
    <DownloadConsole
      status={status({ status: "pruning", waitingInput: true })}
      onCancel={vi.fn()}
      onPruneAnswer={onPruneAnswer}
    />,
  );
  const input = screen.getByPlaceholderText("y / n");
  fireEvent.change(input, { target: { value: "y" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(onPruneAnswer).toHaveBeenCalledWith("y");
});

test("shows downloaded path and no prompt when complete", () => {
  render(
    <DownloadConsole
      status={status({ status: "downloaded", local_path: "/tmp/x" })}
      onCancel={vi.fn()}
      onPruneAnswer={vi.fn()}
    />,
  );
  expect(screen.getByText(/\/tmp\/x/)).toBeInTheDocument();
  expect(screen.queryByPlaceholderText("y / n")).not.toBeInTheDocument();
});

test("shows pruned summary after prune", () => {
  render(
    <DownloadConsole
      status={status({ status: "pruned", pruneAccepted: true })}
      onCancel={vi.fn()}
      onPruneAnswer={vi.fn()}
    />,
  );
  expect(screen.getByText(/cache pruned/i)).toBeInTheDocument();
});

test("shows error message", () => {
  render(
    <DownloadConsole
      status={status({ status: "error", message: "boom" })}
      onCancel={vi.fn()}
      onPruneAnswer={vi.fn()}
    />,
  );
  expect(screen.getByText(/boom/)).toBeInTheDocument();
});
