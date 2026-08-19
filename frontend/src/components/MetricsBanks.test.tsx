import { render, screen } from "@testing-library/react";
import { MetricsBanks } from "./MetricsBanks";

test("renders the agentic bank label and value when agenticTps is present", () => {
  render(<MetricsBanks promptTps={100.0} decodeTps={10.0} agenticTps={25.0} />);
  expect(screen.getByText(/AGENTIC/)).toBeInTheDocument();
  expect(screen.getByText("25.0")).toBeInTheDocument();
});

test("shows a dash in the agentic bank when agenticTps is null", () => {
  render(<MetricsBanks promptTps={100.0} decodeTps={10.0} agenticTps={null} />);
  expect(screen.getByText("—")).toBeInTheDocument();
  expect(screen.queryByText("25.0")).not.toBeInTheDocument();
});

test("highlights the agentic bank as best when agenticTps is present", () => {
  const { container } = render(<MetricsBanks promptTps={100.0} decodeTps={10.0} agenticTps={25.0} best />);
  const best = container.querySelector(".digit-best");
  expect(best?.textContent).toBe("25.0");
});

test("highlights the decode bank as best when agenticTps is null", () => {
  const { container } = render(<MetricsBanks promptTps={100.0} decodeTps={10.0} agenticTps={null} best />);
  const best = container.querySelector(".digit-best");
  expect(best?.textContent).toBe("10.0");
});