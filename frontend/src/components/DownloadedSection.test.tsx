import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { DownloadedSection } from "./DownloadedSection";

const SAMPLE = [
  { server_id: "llama.cpp", repo_id: "org/model", status: "downloaded", gguf_filename: null },
  { server_id: "llama.cpp", repo_id: "org/model", status: "downloaded", gguf_filename: "model.gguf" },
];

function renderSection(props?: Partial<Parameters<typeof DownloadedSection>[0]>) {
  return render(
    <DownloadedSection
      models={SAMPLE}
      onLoad={vi.fn()}
      onRemove={vi.fn()}
      {...props}
    />,
  );
}

test("groups one model across servers into a single row with a file-qualified ref", () => {
  renderSection();
  expect(screen.getByText("org/model/model.gguf")).toBeInTheDocument();
  expect(screen.getByText("llama.cpp")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "LOAD" })).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: "REMOVE" })).toHaveLength(1);
});

test("renders separate rows for distinct models", () => {
  renderSection({
    models: [
      { server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" },
      { server_id: "llama.cpp", repo_id: "org/other", status: "downloaded" },
    ],
  });
  expect(screen.getAllByRole("button", { name: "LOAD" })).toHaveLength(2);
  expect(screen.getByText("org/model")).toBeInTheDocument();
  expect(screen.getByText("org/other")).toBeInTheDocument();
});

test("LOAD calls onLoad with the file-qualified ref when a gguf is present", () => {
  const onLoad = vi.fn();
  renderSection({ onLoad });
  fireEvent.click(screen.getByRole("button", { name: "LOAD" }));
  expect(onLoad).toHaveBeenCalledWith("org/model/model.gguf");
});

test("LOAD calls onLoad with the repo id when no file is known", () => {
  const onLoad = vi.fn();
  renderSection({
    models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" }],
    onLoad,
  });
  fireEvent.click(screen.getByRole("button", { name: "LOAD" }));
  expect(onLoad).toHaveBeenCalledWith("org/model");
});

test("REMOVE confirms then calls onRemove with the repo id", () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const onRemove = vi.fn();
  renderSection({ onRemove });
  fireEvent.click(screen.getByRole("button", { name: "REMOVE" }));
  expect(onRemove).toHaveBeenCalledWith("org/model");
});

test("REMOVE without confirmation does not call onRemove", () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  const onRemove = vi.fn();
  renderSection({ onRemove });
  fireEvent.click(screen.getByRole("button", { name: "REMOVE" }));
  expect(onRemove).not.toHaveBeenCalled();
});

test("does not render rows for non-downloaded models", () => {
  renderSection({ models: [{ server_id: "llama.cpp", repo_id: "org/model", status: "missing" }] });
  expect(screen.queryByText("org/model")).not.toBeInTheDocument();
});

test("lists only downloaded servers when a model has mixed statuses", () => {
  renderSection({
    models: [
      { server_id: "llama.cpp", repo_id: "org/model", status: "downloaded" },
      { server_id: "llama.cpp", repo_id: "org/model", status: "missing" },
    ],
  });
  expect(screen.getByText("llama.cpp")).toBeInTheDocument();
});
