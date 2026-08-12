export interface Lang {
  code: string;
  label: string;
}

export const LANGS: Lang[] = [
  { code: "en", label: "Reset(English)" },
  { code: "zh", label: "中文（简体）" },
  { code: "ja", label: "日本語" },
  { code: "de", label: "Deutsch" },
  { code: "fr", label: "Français" },
  { code: "es", label: "Español" },
  { code: "ko", label: "한국어" },
  { code: "ar", label: "العربية" },
  { code: "pt", label: "Português" },
  { code: "it", label: "Italiano" },
  { code: "nl", label: "Nederlands" },
  { code: "sv", label: "Svenska" },
  { code: "no", label: "Norsk" },
  { code: "da", label: "Dansk" },
  { code: "fi", label: "Suomi" },
];

export const SUPPORTED = new Set(LANGS.map((l) => l.code));
export const STORAGE_KEY = "llmbench.lng";
