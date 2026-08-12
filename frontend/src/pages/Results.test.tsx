import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Results } from "./Results";

vi.mock("../api/client", () => ({
  api: {
    clearRuns: vi.fn().mockResolvedValue({ ok: true }),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

function renderResults(initialRuns: Parameters<typeof Results>[0]["initialRuns"]) {
  return render(
    <MemoryRouter initialEntries={["/results"]}>
      <Routes>
        <Route path="/results" element={<Results initialRuns={initialRuns} />} />
      </Routes>
    </MemoryRouter>,
  );
}

const RUNS = [
  { id: 1, repo_id: "org/model", requested_n: 2, created_at: "", status: "completed" },
];

test("shows empty state when no runs", () => {
  renderResults([]);
  expect(screen.getByText(/no benchmark runs yet/i)).toBeInTheDocument();
});

test("CLEAR HISTORY confirms then calls clearRuns and shows the empty state", async () => {
  const { api } = await import("../api/client");
  vi.spyOn(window, "confirm").mockReturnValue(true);
  renderResults(RUNS);
  fireEvent.click(screen.getByRole("button", { name: /clear history/i }));
  expect(window.confirm).toHaveBeenCalledWith(expect.stringMatching(/clear all benchmark history/i));
  await waitFor(() => expect(api.clearRuns).toHaveBeenCalledTimes(1));
  expect(screen.getByText(/no benchmark runs yet/i)).toBeInTheDocument();
});

test("CLEAR HISTORY without confirmation does not call clearRuns", async () => {
  const { api } = await import("../api/client");
  vi.spyOn(window, "confirm").mockReturnValue(false);
  renderResults(RUNS);
  fireEvent.click(screen.getByRole("button", { name: /clear history/i }));
  expect(api.clearRuns).not.toHaveBeenCalled();
  expect(screen.getByText(/#1 · org\/model/i)).toBeInTheDocument();
});

test("CLEAR HISTORY is disabled while a run is active", () => {
  renderResults([
    { id: 1, repo_id: "org/model", requested_n: 1, created_at: "", status: "running" },
  ]);
  expect(screen.getByRole("button", { name: /clear history/i })).toBeDisabled();
});
