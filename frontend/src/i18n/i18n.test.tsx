import { render, screen } from "@testing-library/react";
import { useTranslation } from "react-i18next";
import i18n from "./index";

function Sample() {
  const { t } = useTranslation();
  return <button>{t("common.runBenchmark")}</button>;
}

afterEach(async () => {
  await i18n.changeLanguage("en");
});

test("renders German content after switching language", async () => {
  render(<Sample />);
  expect(screen.getByText("RUN BENCHMARK")).toBeInTheDocument();
  await i18n.changeLanguage("de");
  expect(screen.getByText(/benchmark ausführen/i)).toBeInTheDocument();
});

test("falls back to English for a missing key", async () => {
  await i18n.changeLanguage("de");
  render(<Sample />);
  expect(screen.getByText(/benchmark ausführen/i)).toBeInTheDocument();
});
