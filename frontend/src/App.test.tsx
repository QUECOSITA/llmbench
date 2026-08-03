import { render, screen } from "@testing-library/react";
import { App } from "./App";

test("renders the instrument header with panel structure", () => {
  render(<App />);
  const header = screen.getByText(/LLM\s*BENCH/i);
  expect(header).toBeInTheDocument();
  expect(document.querySelector(".instrument")).not.toBeNull();
});
