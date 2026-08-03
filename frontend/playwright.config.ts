import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:5173" },
  webServer: [
    { command: "npm run dev", port: 5173 },
    { command: "npx tsx e2e/mock-server.ts", port: 8000 },
  ],
});
