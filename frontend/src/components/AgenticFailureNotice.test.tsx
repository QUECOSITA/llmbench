import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { AgenticFailureNotice } from "./AgenticFailureNotice";

const notice = {
  key: "context_overflow",
  message: "Context overflow: the injected filler + --ctx-size exceeds the model's context window.",
  tier: "heavy",
  details: "llama-server: request (207154 tokens) exceeds the available context size (131072 tokens)",
};

describe("AgenticFailureNotice", () => {
  test("renders the failure message, tier, and raw details", () => {
    render(<AgenticFailureNotice notice={notice} onDismiss={() => {}} />);
    expect(screen.getByText(/Context overflow/)).toBeTruthy();
    expect(screen.getByText(/tier heavy/i)).toBeTruthy();
    expect(screen.getByText(/207154 tokens/)).toBeTruthy();
  });

  test("DISMISS calls onDismiss", () => {
    const onDismiss = vi.fn();
    render(<AgenticFailureNotice notice={notice} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByText("DISMISS"));
    expect(onDismiss).toHaveBeenCalled();
  });

  test("renders without details when none provided", () => {
    render(<AgenticFailureNotice notice={{ ...notice, details: undefined }} onDismiss={() => {}} />);
    expect(screen.getByText(/Context overflow/)).toBeTruthy();
  });
});
