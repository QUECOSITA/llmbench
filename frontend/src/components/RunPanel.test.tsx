import { fireEvent, render, screen } from "@testing-library/react";
import { RunPanel } from "./RunPanel";

test("run button disabled while running", () => {
  render(<RunPanel running onRun={vi.fn()} progress={{ index: 1, total: 4 }} />);
  expect(screen.getByText(/run benchmark/i)).toBeDisabled();
  expect(screen.getByText(/1\/4/i)).toBeInTheDocument();
});

test("run button triggers onRun", () => {
  const onRun = vi.fn();
  render(<RunPanel running={false} onRun={onRun} progress={null} />);
  fireEvent.click(screen.getByText(/run benchmark/i));
  expect(onRun).toHaveBeenCalled();
});
