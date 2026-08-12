# Qualitative Default + Speed-Bench Flag Info Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the speed-bench default flags to use the `qualitative` bench (aligning `--osl` with the CLI's `4096`) and show a dynamic info block next to the SPEED-BENCH FLAGS textarea documenting accepted `--bench` / `--category` / `--limit` values.

**Architecture:** The backend's `speed_bench_default_flags()` and `Settings.speed_bench_osl` are updated so generated speed-bench configs default to `--bench qualitative --category all --limit 1 --osl 4096`. A new read-only endpoint `GET /api/speed-bench/info` serializes the existing `SPEED_BENCH_BENCHES` / `SPEED_BENCH_CATEGORIES` constants (single source of truth). The frontend fetches it once at mount, passes it to `ConfigBank`, and renders a small monospace info block under the flags textarea that recomputes the `--category` line from the `--bench` value currently typed in the textarea.

**Tech Stack:** Python FastAPI (backend), TypeScript React + Vitest + Playwright (frontend).

**Design spec:** `docs/superpowers/specs/2026-08-12-qualitative-default-and-flag-info-design.md`

---

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/app/servers.py` | `speed_bench_default_flags()` returns the new qualitative default; constants `SPEED_BENCH_BENCHES` / `SPEED_BENCH_CATEGORIES` unchanged. |
| `backend/app/config.py` | `speed_bench_osl` default 128 → 4096. |
| `backend/app/api.py` | New `GET /api/speed-bench/info` endpoint. |
| `backend/tests/test_servers.py` | Default-flags assertions updated. |
| `backend/tests/test_config.py` | `speed_bench_osl` default assertion updated. |
| `backend/tests/test_api.py` | Generate/rebuild assertions updated; new endpoint test added. |
| `frontend/src/api/client.ts` | `SpeedBenchInfo` type + `api.getSpeedBenchInfo()`. |
| `frontend/src/App.tsx` | Fetch info at mount, pass to `ConfigBank`. |
| `frontend/src/components/ConfigBank.tsx` | `speedBenchInfo` prop + `SpeedBenchFlagInfo` render. |
| `frontend/src/components/ConfigBank.test.tsx` | Info-block render + dynamic category tests; fixture strings updated. |
| `frontend/src/App.test.tsx` | Mock `getSpeedBenchInfo`; fixture strings updated. |
| `frontend/e2e/mock-server.ts` | Serve `/api/speed-bench/info`. |
| `README.md` | Speed-bench bullet updated to qualitative default. |

---

### Task 1: Backend — qualitative default flags + osl 4096

**Files:**
- Modify: `backend/app/servers.py:126-127`
- Modify: `backend/app/config.py:18`
- Test: `backend/tests/test_servers.py:249-251`
- Test: `backend/tests/test_config.py:29`
- Test: `backend/tests/test_api.py:1228,1234-1235,1261,1362`

- [ ] **Step 1: Write the failing backend tests**

In `backend/tests/test_servers.py`, replace `test_speed_bench_default_flags` (lines 249-251):

```python
def test_speed_bench_default_flags():
    assert speed_bench_default_flags() == "--bench qualitative --category all --limit 1 --osl 4096"
    assert speed_bench_default_flags(osl=256) == "--bench qualitative --category all --limit 1 --osl 256"
```

In `backend/tests/test_config.py`, change line 29:

```python
    assert s.speed_bench_osl == 4096
```

In `backend/tests/test_api.py`:

- Line 1228: `assert cfg["bench_flags"] == "--bench qualitative --category all --limit 1 --osl 4096"`
- Line 1234: `assert cmd[cmd.index("--bench") + 1] == "qualitative"`
- Line 1235: `assert cmd[cmd.index("--osl") + 1] == "4096"`
- Line 1261 (in `test_generate_speed_bench_uses_configured_osl`): `assert cfg["bench_flags"] == "--bench qualitative --category all --limit 1 --osl 256"`
- Line 1362 (in `test_rebuild_bench_command_speed_bench_missing_flags_uses_default`): `assert cfg["bench_command"][cfg["bench_command"].index("--bench") + 1] == "qualitative"`

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_servers.py::test_speed_bench_default_flags tests/test_config.py::test_speed_bench_settings_defaults tests/test_api.py::test_generate_speed_bench -x -q`
Expected: FAIL — assertions still see `throughput_1k` / `128`.

- [ ] **Step 3: Implement the new defaults**

In `backend/app/servers.py`, change `speed_bench_default_flags` (lines 126-127):

```python
def speed_bench_default_flags(osl: int = 4096) -> str:
    return f"--bench qualitative --category all --limit 1 --osl {osl}"
```

In `backend/app/config.py`, change line 18:

```python
    speed_bench_osl: int = 4096
```

- [ ] **Step 4: Run the backend tests**

Run: `cd backend && python -m pytest tests/test_servers.py tests/test_config.py tests/test_api.py -q`
Expected: PASS.

- [ ] **Step 5: Update README**

In `README.md` line 22, replace the trailing sentence:

> The speed-bench client always runs with `--limit 1 --category all --bench qualitative --osl 4096`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/servers.py backend/app/config.py backend/tests/test_servers.py backend/tests/test_config.py backend/tests/test_api.py README.md
git commit -m "feat: default speed-bench to qualitative bench with CLI osl 4096"
```

---

### Task 2: Backend — `GET /api/speed-bench/info` endpoint

**Files:**
- Modify: `backend/app/api.py` (imports + endpoint after `/servers`)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py`:

```python
def test_speed_bench_info_endpoint(client):
    from app.servers import SPEED_BENCH_BENCHES, SPEED_BENCH_CATEGORIES
    r = client.get("/api/speed-bench/info")
    assert r.status_code == 200
    body = r.json()
    assert body["benches"] == list(SPEED_BENCH_BENCHES)
    assert body["categories"] == {b: list(c) for b, c in SPEED_BENCH_CATEGORIES.items()}
    assert "qualitative" in body["benches"]
    assert "throughput_1k" in body["benches"]
    assert "coding" in body["categories"]["qualitative"]
    assert "high_entropy" in body["categories"]["throughput_1k"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api.py::test_speed_bench_info_endpoint -x -q`
Expected: FAIL — `404` / route not found.

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api.py`, extend the `app.servers` import (lines 25-29) with the two constants:

```python
from app.servers import (build_bench_command, build_server_command, build_speed_bench_command,
                         detect_binaries, is_spec_decoding_model, model_ref_from_flags,
                         parse_serving_command, resolve_speed_bench_script,
                         speed_bench_deps_available, parse_speed_bench_flags,
                         speed_bench_default_flags, validate_speed_bench_flags,
                         SPEED_BENCH_BENCHES, SPEED_BENCH_CATEGORIES)
```

Add a new endpoint directly after the `servers` handler (after line 187):

```python
@router.get("/speed-bench/info")
async def speed_bench_info():
    return {
        "benches": list(SPEED_BENCH_BENCHES),
        "categories": {bench: list(cats) for bench, cats in SPEED_BENCH_CATEGORIES.items()},
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_api.py::test_speed_bench_info_endpoint -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: expose speed-bench benches/categories via GET /api/speed-bench/info"
```

---

### Task 3: Frontend — client method + type

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/App.test.tsx` a new test that asserts the client exposes `getSpeedBenchInfo` and resolves to the mocked payload (do NOT add the mock entry yet — see Step 3):

```tsx
test("getSpeedBenchInfo returns benches and categories", async () => {
  const { api } = await import("./api/client");
  const info = await api.getSpeedBenchInfo();
  expect(info.benches).toContain("qualitative");
  expect(info.categories.qualitative).toContain("coding");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "getSpeedBenchInfo" 2>&1 | tail -20`
Expected: FAIL — `api.getSpeedBenchInfo is not a function` (the mocked `api` lacks the method).

- [ ] **Step 3: Implement the client method**

In `frontend/src/api/client.ts`, add the type near the other interfaces (after `ConfigFit`):

```ts
export interface SpeedBenchInfo {
  benches: string[];
  categories: Record<string, string[]>;
}
```

Add the method to the `api` object (after `getServers`):

```ts
  getSpeedBenchInfo: () => request<SpeedBenchInfo>("/speed-bench/info"),
```

Add `getSpeedBenchInfo` to the mocked `api` in the `vi.mock` block at the top of `App.test.tsx` (after `getServers`, line 7) so this test and the mount test (Task 5) resolve against the mock:

```ts
    getSpeedBenchInfo: vi.fn().mockResolvedValue({
      benches: ["qualitative", "throughput_1k", "throughput_2k", "throughput_8k", "throughput_16k", "throughput_32k"],
      categories: {
        qualitative: ["coding", "humanities", "math", "qa", "rag", "reasoning", "stem", "writing", "multilingual", "summarization", "roleplay"],
        throughput_1k: ["high_entropy", "mixed", "low_entropy"],
        throughput_2k: ["high_entropy", "mixed", "low_entropy"],
        throughput_8k: ["high_entropy", "mixed", "low_entropy"],
        throughput_16k: ["high_entropy", "mixed", "low_entropy"],
        throughput_32k: ["high_entropy", "mixed", "low_entropy"],
      },
    }),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "getSpeedBenchInfo" 2>&1 | tail -20`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/App.test.tsx
git commit -m "feat: add frontend client method for speed-bench info"
```

---

### Task 4: Frontend — ConfigBank info block (dynamic, bench-aware)

**Files:**
- Modify: `frontend/src/components/ConfigBank.tsx`
- Test: `frontend/src/components/ConfigBank.test.tsx`

- [ ] **Step 1: Write the failing tests**

Update the existing import at the top of `frontend/src/components/ConfigBank.test.tsx` to add the type and component (the type comes from `client.ts`, matching how `ConfigBank.tsx` will import it):

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import type { SpeedBenchInfo } from "../api/client";
import { ConfigBank, ConfigRow, SpeedBenchFlagInfo } from "./ConfigBank";
```

Append the `INFO` fixture and the tests below:

```tsx
const INFO: SpeedBenchInfo = {
  benches: ["qualitative", "throughput_1k", "throughput_2k", "throughput_8k", "throughput_16k", "throughput_32k"],
  categories: {
    qualitative: ["coding", "humanities", "math", "qa", "rag", "reasoning", "stem", "writing", "multilingual", "summarization", "roleplay"],
    throughput_1k: ["high_entropy", "mixed", "low_entropy"],
  },
};

test("renders the accepted benches and limit help", () => {
  render(<SpeedBenchFlagInfo flags="--bench qualitative" info={INFO} />);
  expect(screen.getByText(/--bench:/)).toHaveTextContent("qualitative | throughput_1k");
  expect(screen.getByText(/--limit:/)).toHaveTextContent("max samples per category");
});

test("shows categories for the typed bench", () => {
  render(<SpeedBenchFlagInfo flags="--bench qualitative --category all" info={INFO} />);
  expect(screen.getByText(/--category:/)).toHaveTextContent("coding");
  expect(screen.getByText(/--category:/)).toHaveTextContent("roleplay");
});

test("shows union of categories when bench is empty or unknown", () => {
  const { rerender } = render(<SpeedBenchFlagInfo flags="--category all" info={INFO} />);
  expect(screen.getByText(/--category:/)).toHaveTextContent("coding");
  expect(screen.getByText(/--category:/)).toHaveTextContent("high_entropy");
  rerender(<SpeedBenchFlagInfo flags="--bench bogus" info={INFO} />);
  expect(screen.getByText(/--category:/)).toHaveTextContent("coding");
  expect(screen.getByText(/--category:/)).toHaveTextContent("high_entropy");
});

test("supports --bench=value form", () => {
  render(<SpeedBenchFlagInfo flags="--bench=throughput_1k" info={INFO} />);
  expect(screen.getByText(/--category:/)).toHaveTextContent("high_entropy");
  expect(screen.getByText(/--category:/)).toHaveTextContent("low_entropy");
});
```

Also update the existing speed-bench flags fixture strings in `ConfigBank.test.tsx` (lines 65 and 71) from `--bench throughput_1k --category all --limit 1 --osl 128` to `--bench qualitative --category all --limit 1 --osl 4096`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/ConfigBank.test.tsx 2>&1 | tail -30`
Expected: FAIL — `SpeedBenchFlagInfo is not exported` and fixture text not found.

- [ ] **Step 3: Implement the info block**

In `frontend/src/components/ConfigBank.tsx`, import the type from `client.ts` and add the parser helper and the `SpeedBenchFlagInfo` component. Update the existing import line to:

```tsx
import type { ConfigFit, SpeedBenchInfo } from "../api/client";
```

Then add below the imports:

```tsx
function benchFromFlags(text: string): string | null {
  const m = text.match(/--bench=(\S+)/);
  if (m) return m[1];
  const tokens = text.split(/\s+/);
  for (let i = 0; i < tokens.length - 1; i++) {
    if (tokens[i] === "--bench") return tokens[i + 1];
  }
  return null;
}

export function SpeedBenchFlagInfo({ flags, info }: { flags: string; info: SpeedBenchInfo }) {
  const bench = benchFromFlags(flags);
  const cats =
    bench && info.categories[bench]
      ? info.categories[bench]
      : [...new Set(Object.values(info.categories).flat())];
  return (
    <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--anode)", lineHeight: 1.5 }}>
      <div>--bench: {info.benches.join(" | ")}</div>
      <div>--category: all, or (for bench {bench ?? "…"}): {cats.join(", ")}</div>
      <div>--limit: optional int — max samples per category</div>
    </div>
  );
}
```

Add a new prop to the `Props` interface:

```tsx
interface Props {
  n: number;
  onNChange: (n: number) => void;
  onGenerate: (n: number) => void;
  configs: ConfigRow[];
  canGenerate?: boolean;
  onEdit?: (index: number, command: string) => void;
  onEditFlags?: (index: number, flags: string) => void;
  speedBenchInfo?: SpeedBenchInfo | null;
}
```

Destructure `speedBenchInfo` in the component signature and render it inside the `bench_tool === "speed-bench"` fragment, right after the flags textarea (after line 58):

```tsx
                {speedBenchInfo && (
                  <SpeedBenchFlagInfo flags={cfg.bench_flags ?? ""} info={speedBenchInfo} />
                )}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/ConfigBank.test.tsx 2>&1 | tail -30`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConfigBank.tsx frontend/src/components/ConfigBank.test.tsx
git commit -m "feat: show bench-aware speed-bench flag info in config bank"
```

---

### Task 5: Frontend — App wiring + e2e mock

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/e2e/mock-server.ts`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/App.test.tsx`:

```tsx
test("fetches speed-bench info on mount and passes it to the config bank", async () => {
  const { api } = await import("./api/client");
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
  await waitFor(() => expect(api.getSpeedBenchInfo).toHaveBeenCalled());
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/App.test.tsx -t "speed-bench info on mount" 2>&1 | tail -20`
Expected: FAIL — `getSpeedBenchInfo` never called (App doesn't fetch it yet).

- [ ] **Step 3: Implement App wiring**

In `frontend/src/App.tsx`:
- Add a state hook near the other `useState` calls (near line 118):

```tsx
  const [speedBenchInfo, setSpeedBenchInfo] = useState<SpeedBenchInfo | null>(null);
```

- Import the type at the top (near the existing imports):

```tsx
import type { SpeedBenchInfo } from "./api/client";
```

- Add the fetch to the existing mount `useEffect` (lines 188-191):

```tsx
  useEffect(() => {
    api.getServers().then((d) => setHardware(d.hardware));
    api.listModels().then((d) => setDownloaded(d.models));
    api.getSpeedBenchInfo().then(setSpeedBenchInfo).catch(() => {});
  }, []);
```

- Pass it to `ConfigBank` (add to the props at line ~496):

```tsx
                speedBenchInfo={speedBenchInfo}
```

- [ ] **Step 4: Update App test fixture strings**

In `frontend/src/App.test.tsx`, update the mock `generateConfigs` `bench_flags` value (line 583) and the `getByDisplayValue` query (line 600) from `--bench throughput_1k --category all --limit 1 --osl 128` to `--bench qualitative --category all --limit 1 --osl 4096`. The `fireEvent.change` at line 601 (editing to `--bench qualitative --category coding`) can stay.

- [ ] **Step 5: Add the e2e mock route**

In `frontend/e2e/mock-server.ts`, after the `/api/servers` branch (line 26), add (the mock-server returns `{}` for unmatched routes, so the route is added for correctness/observability rather than to avoid a 404):

```ts
  } else if (req.url?.startsWith("/api/speed-bench/info")) {
    Object.assign(body, {
      benches: ["qualitative", "throughput_1k", "throughput_2k", "throughput_8k", "throughput_16k", "throughput_32k"],
      categories: {
        qualitative: ["coding", "humanities", "math", "qa", "rag", "reasoning", "stem", "writing", "multilingual", "summarization", "roleplay"],
        throughput_1k: ["high_entropy", "mixed", "low_entropy"],
        throughput_2k: ["high_entropy", "mixed", "low_entropy"],
        throughput_8k: ["high_entropy", "mixed", "low_entropy"],
        throughput_16k: ["high_entropy", "mixed", "low_entropy"],
        throughput_32k: ["high_entropy", "mixed", "low_entropy"],
      },
    });
  } else if (req.url?.startsWith("/api/models/analyze")) {
```

(The `else if` chain is already `else if`, so the new branch slots in before the analyze branch.)

- [ ] **Step 6: Run the frontend tests**

Run: `cd frontend && npx tsc -b && npx vitest run 2>&1 | tail -30`
Expected: PASS (typecheck clean, all vitest tests pass).

- [ ] **Step 7: Run the e2e tests**

Run: `cd frontend && npx playwright test 2>&1 | tail -30`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/e2e/mock-server.ts
git commit -m "feat: fetch speed-bench info at mount and wire into config bank"
```

---

### Task 6: Full verification

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS (all tests green).

- [ ] **Step 2: Run the full frontend suite**

Run: `cd frontend && npx tsc -b && npx vitest run && npx playwright test`
Expected: PASS.

- [ ] **Step 3: Confirm no stray references**

Run: `cd /home/ruben/test/llmbench && grep -rn "throughput_1k --category all --limit 1 --osl 128" --include="*.py" --include="*.tsx" --include="*.ts" --include="*.md" . | grep -v docs/superpowers`
Expected: no default-flags references remain. The only tolerated hit is `backend/tests/test_servers.py:255`, which uses that string purely as `parse_speed_bench_flags` input (a parse fixture, not a default assertion) — it can stay.

- [ ] **Step 4: Commit any remaining changes**

```bash
git status
git add -A
git commit -m "chore: finalize qualitative default + speed-bench flag info"
```
