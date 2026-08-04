import { test, expect } from "@playwright/test";

test("full flow: analyze, generate, run, see ranked results", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server vLLM/i)).toBeVisible();
  await expect(page.getByText(/FITS VRAM/i)).toBeVisible();
  await page.getByRole("button", { name: /generate/i }).click();
  await expect(page.getByText(/vllm serve org\/model/i).first()).toBeVisible();
  await expect(page.getByText(/FITS VRAM · 3.8 GB/i)).toBeVisible();
  await page.getByRole("button", { name: /run benchmark/i }).click();
  await expect(page.getByText(/config 0\/1/i).or(page.getByText(/config 1\/1/i))).toBeVisible();
});

test("download console renders with a CANCEL action", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server vLLM/i)).toBeVisible();

  await page.getByRole("button", { name: /^download$/i }).first().click();
  await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
  await page.getByRole("button", { name: /cancel/i }).click();
  await expect(page.getByRole("button", { name: /cancel/i })).toBeVisible();
});
