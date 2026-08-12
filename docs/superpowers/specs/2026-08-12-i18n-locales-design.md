# i18n Locales — Design

**Goal:** Let the user pick a display language for the LLMBENCH UI so it is easier for them to use, with English as the default.

**Languages:** English (default), Mandarin Chinese, Japanese, German, French, Spanish, Korean, Arabic, Portuguese, Italian, Dutch, Swedish, Norwegian, Danish, Finnish.

**Hard requirements**
- User selects a preferred language; the app's general content switches to that language.
- English is the default and appears as the first option, labeled `Reset(English)`.
- Commands, flags, and flag values are never changed or translated.

## Scope of translation

- **Translated (static UI + statuses):** every static label, button, caption, message, and confirm dialog across `App.tsx`, `ModelInput`, `ConfigBank`, `RunPanel`, `DownloadConsole`, `ResultsTable`, `DownloadedSection`, `HardwareBar`, `MetricsBanks`, and the `Results` page; plus display strings for run statuses (running/queued/completed/failed/cancelled/error), download statuses (downloading/downloaded/cancelled/pruning/pruned), result status (ok), and fit-verdict lines (gpu/ram_offload/ram/no_fit).
- **Not translated (kept byte-identical):** the `LLM BENCH` wordmark, server/model names, CLI commands, flags, flag values, the `N` label, the `huggingface.co/Org/model` placeholder, `y`/`n` answers, `y / n` placeholder, the `SPEED-BENCH` badge, `fit.label` from the backend, raw console/log output, and backend error `detail` text.

## Approach

**Library:** `i18next` + `react-i18next` (chosen for future growth over a custom Context solution).

- New `frontend/src/i18n/` module:
  - `locales.ts` — ordered language list (native labels), `SUPPORTED` set, `STORAGE_KEY = "llmbench.lng"`.
  - `index.ts` — `i18next.init({ resources, fallbackLng: "en", lng: stored ?? "en", react: { useSuspense: false } })`. On `languageChanged`: persist to localStorage and set `document.documentElement.lang` and `dir` (rtl for Arabic).
  - `i18next.d.ts` — `CustomTypeOptions` augmentation so `t("...")` keys are compile-time checked against the English template.
  - `status.ts` — `statusLabel(status)` mapping known backend status strings to translation keys.
  - `LocaleSwitcher.tsx` — header `<select>`; first option `Reset(English)`, then the other 14 languages in native script.
  - `locales/{en,zh,ja,de,fr,es,ko,ar,pt,it,nl,sv,no,da,fi}/translation.json` — English is the single source of truth; all locales mirror its keys.
- `main.tsx` imports `./i18n`; `test-setup.ts` imports it too so unit tests get the global English instance.

## Layout adaptation for translated text

- Extend the `--font-mono` stack in `tokens.css` with CJK/Arabic-capable fallbacks (PingFang SC, Hiragino Sans, Meiryo, Malgun Gothic, Noto Sans, Noto Sans Arabic, etc.).
- `.instrument-header` and `.row` get `flex-wrap: wrap` + gap so longer translations wrap instead of overflowing.
- `button` gets `white-space: normal; overflow-wrap: anywhere`.
- `:dir(rtl)` rules right-align `.results-table th/td`.
- `:lang(zh|ja|ko|ar)` rules drop `text-transform` and reduce `letter-spacing` on uppercase-style labels (panel caps, downloaded-server).
- Directional arrows come from translation strings so they point correctly under RTL.

## Persistence

Choice stored under `llmbench.lng` in localStorage. First-time visitors default to English regardless of browser language.

## Testing

- Import `./src/i18n` in `test-setup.ts` → all existing unit tests pass unchanged (English default).
- New unit tests: `LocaleSwitcher.test.tsx` (option list, `Reset(English)` first, change → localStorage + `dir`/`lang`), `i18n.test.tsx` (German content renders after switch, fallback behavior).
- e2e unaffected (default English).
