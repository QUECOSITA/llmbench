import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("renders the instrument header", () => {
  render(<App />);
  expect(screen.getByText(/LLM\s*BENCH/i)).toBeInTheDocument();
});
