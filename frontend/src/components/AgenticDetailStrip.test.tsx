import { render, screen } from "@testing-library/react";
import { AgenticDetailStrip } from "./AgenticDetailStrip";

test("renders agentic detail metrics", () => {
  render(
    <AgenticDetailStrip
      steps={10}
      toolCalls={14}
      planRevisions={2}
      avgMs={1200.0}
      p95Ms={3400.0}
      totalPromptTokens={9000}
      totalCompletionTokens={1600}
    />
  );
  expect(screen.getByText(/10 steps/i)).toBeInTheDocument();
  expect(screen.getByText(/14 tool calls/i)).toBeInTheDocument();
  expect(screen.getByText(/2 plan revs/i)).toBeInTheDocument();
  expect(screen.getByText(/avg 1.2s/i)).toBeInTheDocument();
  expect(screen.getByText(/p95 3.4s/i)).toBeInTheDocument();
  expect(screen.getByText(/ctx 10.6k/i)).toBeInTheDocument();
});

test("renders nothing when no metrics present", () => {
  const { container } = render(<AgenticDetailStrip steps={null} toolCalls={null} planRevisions={null} avgMs={null} p95Ms={null} totalPromptTokens={null} totalCompletionTokens={null} />);
  expect(container.textContent).toBe("");
});
