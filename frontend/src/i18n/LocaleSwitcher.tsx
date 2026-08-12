import { useTranslation } from "react-i18next";
import { LANGS } from "./locales";

export function LocaleSwitcher() {
  const { i18n } = useTranslation();
  return (
    <label style={{ color: "var(--anode)", fontSize: 12 }}>
      language
      <select
        aria-label="language"
        value={i18n.language}
        onChange={(e) => void i18n.changeLanguage(e.target.value)}
        style={{ marginLeft: 6 }}
      >
        {LANGS.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}
