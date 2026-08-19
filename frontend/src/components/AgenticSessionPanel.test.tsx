import { render, screen } from "@testing-library/react";
import { AgenticSessionPanel } from "./AgenticSessionPanel";

const sampleLines = [
  "── step 1/10 ──",
  "CHOICE forced submit_plan",
  "PROMPT Analyze the codebase in /repo.",
  "THINK I will read the main file.",
  "BRANCH → submit_plan",
  "PLAN submitted: [\"a\", \"b\"]",
  "step 1/10: prompt 120 tok + 40 tok in 2.1s",
  "── step 2/10 ──",
  "CHOICE auto",
  "THINK (tool call only)",
  "BRANCH → read_file",
  "TOOL read_file({\"path\": \"/repo/main.py\"})",
  "RESULT import time",
];

test("renders nothing when there are no lines", () => {
  const { container } = render(<AgenticSessionPanel lines={[]} />);
  expect(container.textContent).toBe("");
});

test("renders step headers, choices, thinking, branches, and tool results", () => {
  render(<AgenticSessionPanel lines={sampleLines} />);
  expect(screen.getAllByText(/── step 1\/10 ──/i)).toHaveLength(1);
  expect(screen.getByText(/forced submit_plan/i)).toBeInTheDocument();
  expect(screen.getByText(/I will read the main file/i)).toBeInTheDocument();
  expect(screen.getByText(/→ read_file/i)).toBeInTheDocument();
  expect(screen.getByText(/read_file\(\{\"path\"/i)).toBeInTheDocument();
  expect(screen.getByText(/import time/i)).toBeInTheDocument();
});
