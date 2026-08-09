import { render, screen } from "@testing-library/react";
import { ResultsTable } from "./ResultsTable";

const rows = [
  { server_id: "llama.cpp", flag_conf: { "--max-model-len": "8192" }, prompt_processing_tps: 1200.0, decode_tps: 86.4 },
  { server_id: "llama.cpp", flag_conf: { "--max-model-len": "4096" }, prompt_processing_tps: 900.0, decode_tps: 68.9 },
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
        { server_id: "llama.cpp", flag_conf: {}, prompt_processing_tps: null, decode_tps: null, result_status: "failed" },
        { server_id: "llama.cpp", flag_conf: {}, prompt_processing_tps: 100.0, decode_tps: 42.0, result_status: "ok" },
      ]}
    />
  );
  expect(screen.getByText("failed")).toBeTruthy();
});
