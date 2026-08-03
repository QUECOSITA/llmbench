import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { Results } from "./Results";

test("shows empty state when no runs", () => {
  render(
    <MemoryRouter initialEntries={["/results"]}>
      <Routes>
        <Route path="/results" element={<Results initialRuns={[]} />} />
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByText(/no benchmark runs yet/i)).toBeInTheDocument();
});
