import { fireEvent, render, screen } from "@testing-library/react";
import { ConfigBank, ConfigRow } from "./ConfigBank";

test("renders editable config rows and calls onGenerate with N", () => {
  const onGenerate = vi.fn();
  const configs = [
    { flags: { "--max-model-len": "8192" }, serving_command: "vllm serve m --max-model-len 8192" },
    { flags: { "--max-model-len": "4096" }, serving_command: "vllm serve m --max-model-len 4096" },
  ];
  render(<ConfigBank n={4} onNChange={() => {}} onGenerate={onGenerate} configs={configs} />);
  expect(screen.getByText(/vllm serve m --max-model-len 8192/i)).toBeInTheDocument();
  fireEvent.click(screen.getByText(/generate/i));
  expect(onGenerate).toHaveBeenCalledWith(4);
});

test("edits a serving command", () => {
  const onEdit = vi.fn();
  const configs = [{ flags: {}, serving_command: "vllm serve m" }];
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} onEdit={onEdit} />);
  const textarea = screen.getByDisplayValue("vllm serve m");
  fireEvent.change(textarea, { target: { value: "vllm serve m --max-model-len 16384" } });
  expect(onEdit).toHaveBeenCalled();
});

test("renders fit badge per config row", () => {
  const configs: ConfigRow[] = [
    {
      flags: { "--max-model-len": "8192" },
      serving_command: "vllm serve m --max-model-len 8192",
      fit: { stage: "gpu", label: "FITS VRAM", fits_vram: true, offloaded: false, needed_gb: 14.3, kv_gb: 4.3, weights_gb: 10 },
    },
    {
      flags: { "--max-model-len": "16384" },
      serving_command: "vllm serve m --max-model-len 16384",
      fit: { stage: "no_fit", label: "NO FIT", fits_vram: false, offloaded: false, needed_gb: 22.0, kv_gb: 8.6, weights_gb: 10 },
    },
  ];
  render(<ConfigBank n={2} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(screen.getAllByText(/FITS VRAM · 14\.3 GB/).length).toBe(1);
  expect(screen.getByText(/NO FIT · 22 GB/)).toBeInTheDocument();
});

test("renders no badge when config has no fit data", () => {
  const configs = [{ flags: {}, serving_command: "vllm serve m" }];
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(screen.queryByText(/FITS VRAM|NO FIT|OFFLOADED|CPU ONLY/)).not.toBeInTheDocument();
});

test("renders a SPEED-BENCH badge for speed-bench configs", () => {
  const configs: ConfigRow[] = [
    { flags: {}, serving_command: "llama-server --spec-type draft-mtp", bench_tool: "speed-bench" },
    { flags: {}, serving_command: "llama-server -m x", bench_tool: "llama-bench" },
  ];
  const { container } = render(<ConfigBank n={2} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(container.textContent).toContain("SPEED-BENCH");
});

test("renders and edits a SPEED-BENCH FLAGS textarea for speed-bench configs", () => {
  const onEditFlags = vi.fn();
  const configs: ConfigRow[] = [
    {
      flags: {},
      serving_command: "llama-server --spec-type draft-mtp",
      bench_tool: "speed-bench",
      bench_flags: "--bench throughput_1k --category all --limit 1 --osl 128",
    },
  ];
  render(
    <ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} onEditFlags={onEditFlags} />,
  );
  const textarea = screen.getByDisplayValue("--bench throughput_1k --category all --limit 1 --osl 128");
  fireEvent.change(textarea, { target: { value: "--bench qualitative --category coding" } });
  expect(onEditFlags).toHaveBeenCalledWith(0, "--bench qualitative --category coding");
});

test("does not render the flags textarea for non-speed-bench configs", () => {
  const configs: ConfigRow[] = [{ flags: {}, serving_command: "vllm serve m", bench_tool: "llama-bench" }];
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(screen.queryByDisplayValue(/--bench/)).not.toBeInTheDocument();
});
