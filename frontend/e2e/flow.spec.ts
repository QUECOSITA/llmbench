import { test, expect } from "@playwright/test";

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

test("download console renders with a CANCEL action", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
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
  await expect(page.getByText("llama.cpp")).toBeVisible();
  await expect(page.getByText("org/model")).toBeVisible();
  await page.getByRole("button", { name: "LOAD" }).click();
  await expect(page.getByText(/server llama.cpp/i)).toBeVisible();
  await expect(page.getByPlaceholder(/huggingface/i)).toHaveValue("org/model/model.gguf");
});

test("REMOVE confirms and removes the downloaded row", async ({ page }) => {
  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("http://localhost:5173");
  await expect(page.getByText("llama.cpp")).toBeVisible();
  await expect(page.getByText("org/model")).toHaveCount(1);
  await page.getByRole("button", { name: "REMOVE" }).click();
  await expect(page.getByText("org/model")).toHaveCount(0);
});
