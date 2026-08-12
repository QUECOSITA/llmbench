import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { LANGS, STORAGE_KEY } from "./locales";
import en from "./locales/en/translation.json";
import zh from "./locales/zh/translation.json";
import ja from "./locales/ja/translation.json";
import de from "./locales/de/translation.json";
import fr from "./locales/fr/translation.json";
import es from "./locales/es/translation.json";
import ko from "./locales/ko/translation.json";
import ar from "./locales/ar/translation.json";
import pt from "./locales/pt/translation.json";
import it from "./locales/it/translation.json";
import nl from "./locales/nl/translation.json";
import sv from "./locales/sv/translation.json";
import no from "./locales/no/translation.json";
import da from "./locales/da/translation.json";
import fi from "./locales/fi/translation.json";

const stored = typeof localStorage !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
const initial = stored && LANGS.some((l) => l.code === stored) ? stored : "en";

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    zh: { translation: zh },
    ja: { translation: ja },
    de: { translation: de },
    fr: { translation: fr },
    es: { translation: es },
    ko: { translation: ko },
    ar: { translation: ar },
    pt: { translation: pt },
    it: { translation: it },
    nl: { translation: nl },
    sv: { translation: sv },
    no: { translation: no },
    da: { translation: da },
    fi: { translation: fi },
  },
  lng: initial,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  react: { useSuspense: false },
});

i18n.on("languageChanged", (lng) => {
  if (typeof localStorage !== "undefined") localStorage.setItem(STORAGE_KEY, lng);
  document.documentElement.lang = lng;
  document.documentElement.dir = lng === "ar" ? "rtl" : "ltr";
});

export default i18n;
