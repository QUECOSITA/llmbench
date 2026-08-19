import { render, screen } from "@testing-library/react";
import { ResultsTable } from "./ResultsTable";

const rows = [
  { server_id: "llama.cpp", flag_conf: { "--max-model-len": "8192" }, prompt_processing_tps: 1200.0, decode_tps: 86.4, agentic_tps: null },
  { server_id: "llama.cpp", flag_conf: { "--max-model-len": "4096" }, prompt_processing_tps: 900.0, decode_tps: 68.9, agentic_tps: null },
];

test("ranks rows by decode t/s descending", () => {
  render(<ResultsTable rows={rows} />);
  const cells = screen.getAllByText(/\d+\.\d/);
  const first = cells.find((c) => c.textContent === "86.4");
  const second = cells.find((c) => c.textContent === "68.9");
  expect(first!.compareDocumentPosition(second!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("shows result status when metrics are null", () => {
  render(
    <ResultsTable
      rows={[
        { server_id: "llama.cpp", flag_conf: {}, prompt_processing_tps: null, decode_tps: null, agentic_tps: null, result_status: "failed" },
        { server_id: "llama.cpp", flag_conf: {}, prompt_processing_tps: 100.0, decode_tps: 42.0, agentic_tps: null, result_status: "ok" },
      ]}
    />
  );
  expect(screen.getByText("failed")).toBeTruthy();
});

test("ranks rows by agentic t/s descending when present", () => {
  const rows = [
    { server_id: "low", flag_conf: {}, prompt_processing_tps: 100.0, decode_tps: 50.0, agentic_tps: 10.0 },
    { server_id: "high", flag_conf: {}, prompt_processing_tps: 100.0, decode_tps: 50.0, agentic_tps: 30.0 },
  ];
  render(<ResultsTable rows={rows} />);
  const cells = screen.getAllByText(/\d+\.\d/);
  const high = cells.find((c) => c.textContent === "30.0");
  const low = cells.find((c) => c.textContent === "10.0");
  expect(high!.compareDocumentPosition(low!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("renders AGENTIC t/s values", () => {
  render(
    <ResultsTable
      rows={[{ server_id: "llama.cpp", flag_conf: {}, prompt_processing_tps: 100.0, decode_tps: 50.0, agentic_tps: 12.3 }]}
    />
  );
  expect(screen.getByText("12.3")).toBeInTheDocument();
});

test("highlights the agentic cell as best when agentic_tps is present", () => {
  const { container } = render(
    <ResultsTable
      rows={[{ server_id: "llama.cpp", flag_conf: {}, prompt_processing_tps: 100.0, decode_tps: 50.0, agentic_tps: 12.3 }]}
    />
  );
  const best = container.querySelector(".digit-best");
  expect(best?.textContent).toBe("12.3");
});

test("highlights the decode cell as best when agentic_tps is absent", () => {
  const { container } = render(
    <ResultsTable
      rows={[{ server_id: "llama.cpp", flag_conf: {}, prompt_processing_tps: 100.0, decode_tps: 50.0, agentic_tps: null }]}
    />
  );
  const best = container.querySelector(".digit-best");
  expect(best?.textContent).toBe("50.0");
});
