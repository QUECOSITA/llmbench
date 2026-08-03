import { render, screen } from "@testing-library/react";
import { ResultsTable } from "./ResultsTable";

const rows = [
  { server_id: "vllm", flag_conf: { "--max-model-len": "8192" }, prompt_processing_tps: 1200.0, decode_tps: 86.4 },
  { server_id: "sglang", flag_conf: { "--max-model-len": "4096" }, prompt_processing_tps: 900.0, decode_tps: 68.9 },
];

test("ranks rows by decode t/s descending", () => {
  render(<ResultsTable rows={rows} />);
  const cells = screen.getAllByText(/\d+\.\d/);
  const first = cells.find((c) => c.textContent === "86.4");
  const second = cells.find((c) => c.textContent === "68.9");
  expect(first!.compareDocumentPosition(second!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});
