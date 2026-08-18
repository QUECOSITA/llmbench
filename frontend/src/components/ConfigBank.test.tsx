import { fireEvent, render, screen } from "@testing-library/react";
import type { SpeedBenchInfo } from "../api/client";
import { ConfigBank, ConfigRow, SpeedBenchFlagInfo } from "./ConfigBank";

test("renders editable config rows and calls onGenerate with N", () => {
  const onGenerate = vi.fn();
  const configs = [
    { flags: { "--max-model-len": "8192", "--load-mode": "none", "--no-mmproj": "" }, serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 8192" },
    { flags: { "--max-model-len": "4096", "--load-mode": "none", "--no-mmproj": "" }, serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 4096" },
  ];
  render(<ConfigBank n={4} onNChange={() => {}} onGenerate={onGenerate} configs={configs} />);
  expect(screen.getByText(/llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 8192/i)).toBeInTheDocument();
  fireEvent.click(screen.getByText(/generate/i));
  expect(onGenerate).toHaveBeenCalledWith(4);
});

test("edits a serving command", () => {
  const onEdit = vi.fn();
  const configs = [{ flags: {}, serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj" }];
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} onEdit={onEdit} />);
  const textarea = screen.getByDisplayValue("llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj");
  fireEvent.change(textarea, { target: { value: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 16384" } });
  expect(onEdit).toHaveBeenCalled();
});

test("renders fit badge per config row", () => {
  const configs: ConfigRow[] = [
    {
      flags: { "--max-model-len": "8192", "--load-mode": "none", "--no-mmproj": "" },
      serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 8192",
      fit: { stage: "gpu", label: "FITS VRAM", fits_vram: true, offloaded: false, needed_gb: 14.3, kv_gb: 4.3, weights_gb: 10 },
    },
    {
      flags: { "--max-model-len": "16384", "--load-mode": "none", "--no-mmproj": "" },
      serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj --ctx-size 16384",
      fit: { stage: "no_fit", label: "NO FIT", fits_vram: false, offloaded: false, needed_gb: 22.0, kv_gb: 8.6, weights_gb: 10 },
    },
  ];
  render(<ConfigBank n={2} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(screen.getAllByText(/FITS VRAM · 14\.3 GB/).length).toBe(1);
  expect(screen.getByText(/NO FIT · 22 GB/)).toBeInTheDocument();
});

test("renders no badge when config has no fit data", () => {
  const configs = [{ flags: {}, serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj" }];
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(screen.queryByText(/FITS VRAM|NO FIT|OFFLOADED|CPU ONLY/)).not.toBeInTheDocument();
});

test("renders a SPEED-BENCH badge for speed-bench configs", () => {
  const configs: ConfigRow[] = [
    { flags: {}, serving_command: "llama-server --load-mode none --no-mmproj --spec-type draft-mtp", bench_tool: "speed-bench" },
    { flags: {}, serving_command: "llama-server --load-mode none --no-mmproj -m x", bench_tool: "llama-bench" },
  ];
  const { container } = render(<ConfigBank n={2} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(container.textContent).toContain("SPEED-BENCH");
});

test("renders and edits a SPEED-BENCH FLAGS textarea for speed-bench configs", () => {
  const onEditFlags = vi.fn();
  const configs: ConfigRow[] = [
    {
      flags: {},
      serving_command: "llama-server --load-mode none --no-mmproj --spec-type draft-mtp",
      bench_tool: "speed-bench",
      bench_flags: "--bench qualitative --category all --limit 1 --osl 528",
    },
  ];
  render(
    <ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} onEditFlags={onEditFlags} />,
  );
  const textarea = screen.getByDisplayValue("--bench qualitative --category all --limit 1 --osl 528");
  fireEvent.change(textarea, { target: { value: "--bench qualitative --category coding" } });
  expect(onEditFlags).toHaveBeenCalledWith(0, "--bench qualitative --category coding");
});

test("does not render the flags textarea for non-speed-bench configs", () => {
  const configs: ConfigRow[] = [{ flags: {}, serving_command: "llama-server --hf-repo m --hf-file model.gguf --load-mode none --no-mmproj", bench_tool: "llama-bench" }];
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(screen.queryByDisplayValue(/--bench/)).not.toBeInTheDocument();
});

const INFO: SpeedBenchInfo = {
  benches: ["qualitative", "throughput_1k", "throughput_2k", "throughput_8k", "throughput_16k", "throughput_32k"],
  categories: {
    qualitative: ["coding", "humanities", "math", "qa", "rag", "reasoning", "stem", "writing", "multilingual", "summarization", "roleplay"],
    throughput_1k: ["high_entropy", "mixed", "low_entropy"],
  },
};

test("renders the accepted benches and limit help", () => {
  render(<SpeedBenchFlagInfo flags="--bench qualitative" info={INFO} />);
  expect(screen.getByText(/--bench:/)).toHaveTextContent("qualitative | throughput_1k");
  expect(screen.getByText(/--limit:/)).toHaveTextContent("max samples per category");
});

test("shows categories for the typed bench", () => {
  render(<SpeedBenchFlagInfo flags="--bench qualitative --category all" info={INFO} />);
  expect(screen.getByText(/--category:/)).toHaveTextContent("coding");
  expect(screen.getByText(/--category:/)).toHaveTextContent("roleplay");
});

test("shows union of categories when bench is empty or unknown", () => {
  const { rerender } = render(<SpeedBenchFlagInfo flags="--category all" info={INFO} />);
  expect(screen.getByText(/--category:/)).toHaveTextContent("coding");
  expect(screen.getByText(/--category:/)).toHaveTextContent("high_entropy");
  rerender(<SpeedBenchFlagInfo flags="--bench bogus" info={INFO} />);
  expect(screen.getByText(/--category:/)).toHaveTextContent("coding");
  expect(screen.getByText(/--category:/)).toHaveTextContent("high_entropy");
});

test("supports --bench=value form", () => {
  render(<SpeedBenchFlagInfo flags="--bench=throughput_1k" info={INFO} />);
  expect(screen.getByText(/--category:/)).toHaveTextContent("high_entropy");
  expect(screen.getByText(/--category:/)).toHaveTextContent("low_entropy");
});

test("renders the bench tool selector when showBenchToolSelector is true", () => {
  render(
    <ConfigBank
      n={1}
      onNChange={() => {}}
      onGenerate={() => {}}
      configs={[]}
      showBenchToolSelector
      benchTool="llama-bench"
      onBenchToolChange={() => {}}
    />,
  );
  expect(screen.getByLabelText(/bench tool/i)).toBeInTheDocument();
});

test("hides the bench tool selector when showBenchToolSelector is false", () => {
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={[]} />);
  expect(screen.queryByLabelText(/bench tool/i)).not.toBeInTheDocument();
});

test("fires onBenchToolChange on selection", () => {
  const onBenchToolChange = vi.fn();
  render(
    <ConfigBank
      n={1}
      onNChange={() => {}}
      onGenerate={() => {}}
      configs={[]}
      showBenchToolSelector
      benchTool="llama-bench"
      onBenchToolChange={onBenchToolChange}
    />,
  );
  fireEvent.change(screen.getByLabelText(/bench tool/i), { target: { value: "speed-bench" } });
  expect(onBenchToolChange).toHaveBeenCalledWith("speed-bench");
});

test("disables the bench tool selector when canGenerate is false", () => {
  render(
    <ConfigBank
      n={1}
      onNChange={() => {}}
      onGenerate={() => {}}
      configs={[]}
      canGenerate={false}
      showBenchToolSelector
      benchTool="llama-bench"
      onBenchToolChange={() => {}}
    />,
  );
  expect(screen.getByLabelText(/bench tool/i)).toBeDisabled();
});
