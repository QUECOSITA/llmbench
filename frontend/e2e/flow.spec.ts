import { test, expect } from "@playwright/test";

test("language switcher changes the UI language and sets RTL for Arabic", async ({ page }) => {
  await page.goto("http://localhost:5173");
  const select = page.getByLabel("language");
  await expect(select.locator("option").first()).toHaveText("Reset(English)");
  await expect(page.getByRole("button", { name: "ANALYZE" })).toBeVisible();

  await select.selectOption("de");
  await expect(page.getByRole("button", { name: "ANALYSIEREN" })).toBeVisible();
  await expect(select).toHaveValue("de");

  await select.selectOption("ar");
  await expect(page.getByRole("button", { name: "تحليل" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
});

test("full flow: analyze, generate, run, see ranked results", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server llama.cpp/i)).toBeVisible();
  await expect(page.getByText(/FITS VRAM/i)).toBeVisible();
  await page.getByRole("button", { name: /generate/i }).click();
  await expect(page.getByText(/llama-server/i).first()).toBeVisible();
  await expect(page.getByText(/FITS VRAM · 3.8 GB/i)).toBeVisible();
  await page.getByRole("button", { name: /run benchmark/i }).click();
  await expect(page.getByText(/config 0\/1/i).or(page.getByText(/config 1\/1/i))).toBeVisible();
  await expect(page.getByRole("cell", { name: "42.0" })).toBeVisible();
  await expect(page.getByRole("button", { name: /run benchmark/i })).toBeEnabled();
});

test("RUN toggles to CANCEL and back after cancelling", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server llama.cpp/i)).toBeVisible();
  await page.getByRole("button", { name: /generate/i }).click();
  await expect(page.getByText(/llama-server/i).first()).toBeVisible();
  await page.getByRole("button", { name: /run benchmark/i }).click();
  await expect(page.getByRole("button", { name: /cancel benchmark/i })).toBeVisible();
  await page.getByRole("button", { name: /cancel benchmark/i }).click();
  await expect(page.getByRole("button", { name: /run benchmark/i })).toBeEnabled();
});

test("download console renders with a CANCEL action", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/dl");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server llama.cpp/i)).toBeVisible();

  await page.getByRole("button", { name: /^download$/i }).first().click();
  await expect(page.locator(".dl-console")).toBeVisible();
  await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
  await page.getByRole("button", { name: /cancel/i }).click();
  await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
});

test("LOAD fills the model input with the README-proposed downloaded model and analyzes it", async ({ page }) => {
  await page.goto("http://localhost:5173");
  const modelRow = page.locator(".downloaded-row", { hasText: "org/model" });
  await expect(modelRow).toBeVisible();
  await expect(page.getByText("org/model")).toBeVisible();
  await modelRow.getByRole("button", { name: "LOAD" }).click();
  await expect(page.getByText(/server llama.cpp/i)).toBeVisible();
  await expect(page.getByPlaceholder(/huggingface/i)).toHaveValue("org/model/model.gguf");
});

test("REMOVE confirms and removes the downloaded row", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("http://localhost:5173");
  await expect(page.locator(".downloaded-row", { hasText: "org/model" })).toBeVisible();
  await expect(page.getByText("org/model")).toHaveCount(1);
  await page.locator(".downloaded-row", { hasText: "org/model" }).getByRole("button", { name: "REMOVE" }).click();
  await expect(page.getByText("org/model")).toHaveCount(0);
});

test("warns when README has no serving command and requires confirmation to download", async ({ page }) => {
  await page.goto("http://localhost:5173");
  const input = page.getByPlaceholder(/model/i);
  await input.fill("org/noserve");
  await page.getByRole("button", { name: /analyze/i }).click();
  await page.getByText(/may not be loadable by LLMBENCH/i).waitFor();
  await page.getByText(/YES — DOWNLOAD ANYWAY/i).waitFor();
  await expect(page.getByRole("button", { name: "Download", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: /YES — DOWNLOAD ANYWAY/i }).click();
  await page.getByRole("button", { name: "Download", exact: true }).waitFor();
});

test("CLEAR HISTORY empties the results list", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("http://localhost:5173/results");
  await expect(page.getByText(/#1 · org\/model/i)).toBeVisible();
  await page.getByRole("button", { name: /clear history/i }).click();
  await expect(page.getByText(/no benchmark runs yet/i)).toBeVisible();
});

test("multi-gguf: analyze lists files as checkboxes and download only selected", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/multi");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/File\(model\.Q4_K_M\.gguf\)/i)).toBeVisible();
  await expect(page.getByText(/File\(model\.Q8_0\.gguf\)/i)).toBeVisible();
  const downloadBtn = page.getByRole("button", { name: "Download" });
  await expect(downloadBtn).toBeDisabled();
  await page.getByRole("checkbox").first().check();
  await expect(downloadBtn).toBeEnabled();
  await downloadBtn.click();
  await expect(page.locator(".dl-console")).toBeVisible();
});
