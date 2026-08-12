import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "./index";
import { LocaleSwitcher } from "./LocaleSwitcher";
import { LANGS, STORAGE_KEY } from "./locales";

afterEach(async () => {
  await i18n.changeLanguage("en");
  localStorage.clear();
});

test("lists Reset(English) first, then every supported language in native script", () => {
  render(<LocaleSwitcher />);
  const select = screen.getByLabelText("language") as HTMLSelectElement;
  const labels = [...select.querySelectorAll("option")].map((o) => o.textContent);
  expect(labels[0]).toBe("Reset(English)");
  expect(labels).toEqual(LANGS.map((l) => l.label));
});

test("changing language persists to localStorage and sets lang/dir", async () => {
  render(<LocaleSwitcher />);
  fireEvent.change(screen.getByLabelText("language"), { target: { value: "ar" } });
  await waitFor(() => expect(localStorage.getItem(STORAGE_KEY)).toBe("ar"));
  expect(document.documentElement.lang).toBe("ar");
  expect(document.documentElement.dir).toBe("rtl");

  fireEvent.change(screen.getByLabelText("language"), { target: { value: "de" } });
  await waitFor(() => expect(localStorage.getItem(STORAGE_KEY)).toBe("de"));
  expect(document.documentElement.lang).toBe("de");
  expect(document.documentElement.dir).toBe("ltr");
});
