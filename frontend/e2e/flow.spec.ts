import { test, expect } from "@playwright/test";

test("full flow: analyze, generate, run, see ranked results", async ({ page }) => {
  await page.goto("http://localhost:5173");
  await page.getByPlaceholder(/huggingface/i).fill("org/model");
  await page.getByRole("button", { name: /analyze/i }).click();
  await expect(page.getByText(/server vLLM/i)).toBeVisible();
  await page.getByRole("button", { name: /generate/i }).click();
  await expect(page.getByText(/vllm serve org\/model/i).first()).toBeVisible();
  await page.getByRole("button", { name: /run benchmark/i }).click();
  await expect(page.getByText(/config 0\/1/i).or(page.getByText(/config 1\/1/i))).toBeVisible();
});
