# Editable Speed-Bench Flags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users edit speed-bench client flags per config in the bank (`--bench throughput_1k --category all --limit 1 --osl 128` by default); validate the flags against the speed-bench CLI and SPEED-Bench dataset variants at run start, rejecting invalid flags/values with a clear 422.

**Architecture:** A second editable textarea per speed-bench config row round-trips a `bench_flags` string like `serving_command`. Backend helpers parse (`shlex`) and statically validate the flags; `_rebuild_bench_command` runs the validation at run start, setting `bench_error` → 422 on failure, otherwise rebuilding the `bench_command` from the validated tokens plus app-managed `--url`/`--output`.

**Tech Stack:** Python (FastAPI, shlex, importlib), TypeScript (React + Vite, vitest + testing-library, Playwright).

---

## File Structure

- `backend/app/servers.py` — add `SPEED_BENCH_CLI_FLAGS`, `SPEED_BENCH_BENCHES`, `SPEED_BENCH_CATEGORIES`, `speed_bench_default_flags`, `parse_speed_bench_flags`, `validate_speed_bench_flags`, `_speed_bench_categories`; change `build_speed_bench_command` signature from `(script, osl=128, url, output)` to `(script, flags: list[str], url, output)`.
- `backend/app/api.py` — generate sets `cfg["bench_flags"]`; `_rebuild_bench_command` parses/validates `bench_flags` and rebuilds the command.
- `backend/tests/test_servers.py` — tests for the new helpers + updated `build_speed_bench_command` shape test.
- `backend/tests/test_api.py` — generate default `bench_flags`, edited-flags rebuild, invalid-flags 422.
- `frontend/src/api/client.ts` — `bench_flags?: string` in the generate response config type.
- `frontend/src/components/ConfigBank.tsx` — `bench_flags` field + `onEditFlags` prop + second textarea.
- `frontend/src/App.tsx` — `onEditFlags` handler + round-trip `bench_flags` in the run payload.
- `frontend/src/components/ConfigBank.test.tsx`, `frontend/src/App.test.tsx` — frontend tests.

---

### Task 1: Backend flag parsing + validation helpers (servers.py)

**Files:**
- Modify: `backend/app/servers.py` (add helpers after `resolve_speed_bench_script`, around line 116; change `build_speed_bench_command` at line 119)
- Test: `backend/tests/test_servers.py`

- [ ] **Step 1: Write the failing tests**

Update the import at the top of `backend/tests/test_servers.py` (lines 5-6) to:

```python
from app.servers import (is_spec_decoding_model, resolve_serving_binary, resolve_speed_bench_script,
                         build_server_command, build_speed_bench_command, speed_bench_deps_available,
                         parse_speed_bench_flags, validate_speed_bench_flags, speed_bench_default_flags)
```

Add these test functions (replace the old `test_build_speed_bench_command_shape`):

```python
def test_speed_bench_default_flags():
    assert speed_bench_default_flags() == "--bench throughput_1k --category all --limit 1 --osl 128"
    assert speed_bench_default_flags(osl=256) == "--bench throughput_1k --category all --limit 1 --osl 256"


def test_parse_speed_bench_flags_defaults():
    flags = parse_speed_bench_flags("--bench throughput_1k --category all --limit 1 --osl 128")
    assert flags == ["--bench", "throughput_1k", "--category", "all", "--limit", "1", "--osl", "128"]


def test_parse_speed_bench_flags_drops_leading_bare_tokens():
    flags = parse_speed_bench_flags("python3 /x/speed_bench.py --bench qualitative --limit 2")
    assert flags == ["--bench", "qualitative", "--limit", "2"]


def test_parse_speed_bench_flags_extra_flags():
    flags = parse_speed_bench_flags("--bench throughput_1k --concurrency 4 --timeout 120")
    assert flags == ["--bench", "throughput_1k", "--concurrency", "4", "--timeout", "120"]


def test_parse_speed_bench_flags_equals_form():
    flags = parse_speed_bench_flags("--bench=qualitative --category=coding")
    assert flags == ["--bench", "qualitative", "--category", "coding"]


def test_validate_speed_bench_flags_valid():
    assert validate_speed_bench_flags(["--bench", "throughput_1k", "--category", "all", "--limit", "1", "--osl", "128"]) is None


def test_validate_speed_bench_flags_unknown_flag():
    err = validate_speed_bench_flags(["--foo", "bar"])
    assert err is not None and "unknown speed-bench flag '--foo'" in err
    assert "--url" in err and "--output" in err


def test_validate_speed_bench_flags_bad_bench():
    err = validate_speed_bench_flags(["--bench", "foo"])
    assert err is not None and "unknown --bench 'foo'" in err
    assert "throughput_1k" in err


def test_validate_speed_bench_flags_bad_category_per_bench():
    err = validate_speed_bench_flags(["--bench", "throughput_1k", "--category", "coding"])
    assert err is not None and "unknown --category 'coding' for bench 'throughput_1k'" in err
    assert "high_entropy" in err
    err2 = validate_speed_bench_flags(["--bench", "qualitative", "--category", "high_entropy"])
    assert err2 is not None and "unknown --category 'high_entropy' for bench 'qualitative'" in err2


def test_validate_speed_bench_flags_all_category_valid_for_any_bench():
    assert validate_speed_bench_flags(["--bench", "qualitative", "--category", "all"]) is None
    assert validate_speed_bench_flags(["--bench", "throughput_1k", "--category", "all"]) is None


def test_validate_speed_bench_flags_reserved_url_output():
    err = validate_speed_bench_flags(["--url", "localhost:9000"])
    assert err is not None and "managed by the app" in err
    err2 = validate_speed_bench_flags(["--output", "x.json"])
    assert err2 is not None and "managed by the app" in err2


def test_validate_speed_bench_flags_bare_token():
    err = validate_speed_bench_flags(["--bench", "throughput_1k", "stray"])
    assert err is not None and "unexpected token 'stray'" in err


def test_validate_speed_bench_flags_missing_value():
    err = validate_speed_bench_flags(["--osl", "--bench"])
    assert err is not None and "requires a value" in err


def test_build_speed_bench_command_with_flags(tmp_path):
    script = str(tmp_path / "speed_bench.py")
    cmd = build_speed_bench_command(script, ["--bench", "qualitative", "--limit", "2"],
                                    url="localhost:8080", output="/tmp/out.json")
    assert cmd[0] == sys.executable
    assert cmd[1] == script
    assert cmd[cmd.index("--bench") + 1] == "qualitative"
    assert cmd[cmd.index("--limit") + 1] == "2"
    assert cmd[cmd.index("--url") + 1] == "localhost:8080"
    assert cmd[cmd.index("--output") + 1] == "/tmp/out.json"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ruben/test/llmbench/backend && .venv/bin/python -m pytest tests/test_servers.py -q`
Expected: FAIL — `ImportError`/`AttributeError` for `parse_speed_bench_flags`, `validate_speed_bench_flags`, `speed_bench_default_flags`.

- [ ] **Step 3: Implement the helpers and signature change**

In `backend/app/servers.py`, replace `build_speed_bench_command` (lines 119-129) with:

```python
SPEED_BENCH_CLI_FLAGS = ("--url", "--model", "--bench", "--category", "--osl",
                         "--extra-inputs", "--concurrency", "--limit", "--timeout", "--output")

SPEED_BENCH_BENCHES = ("qualitative", "throughput_1k", "throughput_2k",
                       "throughput_8k", "throughput_16k", "throughput_32k")

SPEED_BENCH_CATEGORIES = {
    "qualitative": ("coding", "humanities", "math", "qa", "rag", "reasoning",
                    "stem", "writing", "multilingual", "summarization", "roleplay"),
    "throughput_1k": ("high_entropy", "mixed", "low_entropy"),
    "throughput_2k": ("high_entropy", "mixed", "low_entropy"),
    "throughput_8k": ("high_entropy", "mixed", "low_entropy"),
    "throughput_16k": ("high_entropy", "mixed", "low_entropy"),
    "throughput_32k": ("high_entropy", "mixed", "low_entropy"),
}


def speed_bench_default_flags(osl: int = 128) -> str:
    return f"--bench throughput_1k --category all --limit 1 --osl {osl}"


def parse_speed_bench_flags(text: str) -> list[str]:
    """Split the user-edited flags string into tokens. Drop any leading bare
    tokens (so pasting the full command works) and normalize --flag=value."""
    import shlex
    tokens = shlex.split(text)
    while tokens and not tokens[0].startswith("-"):
        tokens = tokens[1:]
    out: list[str] = []
    for tok in tokens:
        if tok.startswith("--") and "=" in tok:
            name, _, value = tok.partition("=")
            out.extend([name, value])
        else:
            out.append(tok)
    return out


def _speed_bench_categories(bench: str | None) -> set[str]:
    if bench:
        return set(SPEED_BENCH_CATEGORIES.get(bench, ()))
    union: set[str] = set()
    for cats in SPEED_BENCH_CATEGORIES.values():
        union.update(cats)
    return union


def validate_speed_bench_flags(flags: list[str]) -> str | None:
    """Return an error message for invalid speed-bench flags, or None if valid."""
    parsed: dict[str, list[str]] = {}
    i = 0
    while i < len(flags):
        tok = flags[i]
        if not tok.startswith("-"):
            return f"unexpected token '{tok}'"
        name = tok
        value = None
        if i + 1 < len(flags) and not flags[i + 1].startswith("-"):
            value = flags[i + 1]
            i += 1
        if name not in SPEED_BENCH_CLI_FLAGS:
            return f"unknown speed-bench flag '{name}'; allowed: " + ", ".join(SPEED_BENCH_CLI_FLAGS)
        if name in ("--url", "--output"):
            return f"{name} is managed by the app; remove it from the speed-bench flags"
        if value is None:
            return f"flag '{name}' requires a value"
        parsed.setdefault(name, []).append(value)
        i += 1
    for b in parsed.get("--bench", []):
        if b not in SPEED_BENCH_BENCHES:
            return f"unknown --bench '{b}'; available benches: " + ", ".join(SPEED_BENCH_BENCHES)
    bench = parsed["--bench"][0] if parsed.get("--bench") else None
    cats = _speed_bench_categories(bench)
    for c in parsed.get("--category", []):
        if c != "all" and c not in cats:
            avail = "all, " + ", ".join(sorted(cats))
            return f"unknown --category '{c}' for bench '{bench}'; available: {avail}"
    return None


def build_speed_bench_command(script: str, flags: list[str], url: str = "localhost:8080",
                              output: str = "speed-bench.json") -> list[str]:
    return [sys.executable, script, *flags, "--url", url, "--output", output]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ruben/test/llmbench/backend && .venv/bin/python -m pytest tests/test_servers.py -q`
Expected: PASS (53 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/servers.py backend/tests/test_servers.py && git commit -m "feat: parse and validate editable speed-bench flags"
```

---

### Task 2: Generate sets default bench_flags and builds the command from it

**Files:**
- Modify: `backend/app/api.py` (import line 24-27; generate loop lines 494-502)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test updates**

Update `test_generate_configs_llama_spec_readme_uses_speed_bench` (line 1067) to also assert the default flags. Replace the assertions block at lines 1090-1097 with:

```python
    cfg = r.json()["configs"][0]
    assert cfg["bench_tool"] == "speed-bench"
    assert cfg["bench_flags"] == "--bench throughput_1k --category all --limit 1 --osl 128"
    cmd = cfg["bench_command"]
    assert cmd[0] == sys.executable
    assert cmd[1] == str(script)
    assert cmd[cmd.index("--limit") + 1] == "1"
    assert cmd[cmd.index("--category") + 1] == "all"
    assert cmd[cmd.index("--bench") + 1] == "throughput_1k"
    assert cmd[cmd.index("--osl") + 1] == "128"
    assert "draft-mtp" in cfg["serving_command"]
```

Add a new test after it:

```python
def test_generate_speed_bench_uses_configured_osl(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    bin_dir = tmp_path / "llama" / "build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "llama" / "tools" / "server" / "bench" / "speed-bench" / "speed_bench.py"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env python3\n")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir, speed_bench_osl=256)
    (tmp_path / "prompts.jsonl").write_text("{\"prompt\": \"hi\"}\n")
    with TestClient(create_app(settings)) as c:
        r = c.post("/api/configs/generate", json={
            "server_id": "llama.cpp",
            "repo_id": "org/Qwen3-MTP",
            "n": 1,
            "readme_flags": {"--spec-type": "draft-mtp"},
        })
    assert r.status_code == 200
    cfg = r.json()["configs"][0]
    assert cfg["bench_flags"] == "--bench throughput_1k --category all --limit 1 --osl 256"
    assert cfg["bench_command"][cfg["bench_command"].index("--osl") + 1] == "256"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ruben/test/llmbench/backend && .venv/bin/python -m pytest tests/test_api.py::test_generate_configs_llama_spec_readme_uses_speed_bench tests/test_api.py::test_generate_speed_bench_uses_configured_osl -q`
Expected: FAIL — `KeyError: 'bench_flags'` (field not set by generate).

- [ ] **Step 3: Implement generate changes**

In `backend/app/api.py`:

- Add the new imports to the `from app.servers import (...)` at lines 24-27:

```python
from app.servers import (build_bench_command, build_server_command, build_speed_bench_command,
                         detect_binaries, is_spec_decoding_model, model_ref_from_flags,
                         parse_serving_command, resolve_speed_bench_script,
                         speed_bench_deps_available, parse_speed_bench_flags,
                         speed_bench_default_flags, validate_speed_bench_flags)
```

- Replace the generate speed-bench branch (lines 494-502) with:

```python
        if uses_speed_bench:
            script = resolve_speed_bench_script(bin_dir, configured=s.settings.speed_bench_script)
            if script and speed_bench_deps_available():
                flags_text = speed_bench_default_flags(s.settings.speed_bench_osl)
                cfg["bench_flags"] = flags_text
                cfg["bench_command"] = build_speed_bench_command(
                    script, parse_speed_bench_flags(flags_text),
                    output=str(s.settings.data_dir / "speed-bench.json"))
            else:
                cfg["bench_command"] = []
                cfg["bench_error"] = _speed_bench_error(script)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ruben/test/llmbench/backend && .venv/bin/python -m pytest tests/test_api.py -q`
Expected: PASS (50 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/api.py backend/tests/test_api.py && git commit -m "feat: seed default speed-bench flags on generate"
```

---

### Task 3: Rebuild validates edited flags and rejects invalid ones at run start

**Files:**
- Modify: `backend/app/api.py` (`_rebuild_bench_command` lines 537-548)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test updates**

Update `test_rebuild_bench_command_speed_bench` (line 1113) to feed edited flags. Replace the `cfg = {...}` dict (lines 1127-1133) with:

```python
    cfg = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp --port 9999 --host 0.0.0.0",
        "flags": {},
        "bench_flags": "--bench qualitative --category coding --limit 2 --concurrency 4",
        "bench_command": [],
    }
```

And replace the bench_command assertions (lines 1139-1141) with:

```python
    assert cfg["bench_command"][0] == sys.executable
    assert cfg["bench_command"][1] == str(script)
    assert cfg["bench_command"][cfg["bench_command"].index("--bench") + 1] == "qualitative"
    assert cfg["bench_command"][cfg["bench_command"].index("--category") + 1] == "coding"
    assert cfg["bench_command"][cfg["bench_command"].index("--concurrency") + 1] == "4"
    assert "bench_error" not in cfg
```

Add new tests after it:

```python
def test_rebuild_bench_command_speed_bench_invalid_flags(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    from app.api import _rebuild_bench_command, AppState
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "speed_bench.py"
    script.write_text("x")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir, speed_bench_script=script)
    (tmp_path / "prompts.jsonl").write_text("x\n")
    s = AppState(settings)
    cfg = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp",
        "flags": {},
        "bench_flags": "--bench foo",
        "bench_command": [],
    }
    _rebuild_bench_command(s, cfg, "org/model")
    assert cfg["bench_command"] == []
    assert "unknown --bench 'foo'" in cfg["bench_error"]


def test_rebuild_bench_command_speed_bench_missing_flags_uses_default(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    from app.api import _rebuild_bench_command, AppState
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "llama-server").write_text("#!/bin/sh\n")
    script = tmp_path / "speed_bench.py"
    script.write_text("x")
    settings = Settings(data_dir=tmp_path / "data", gguf_dir=tmp_path / "gguf",
                        hf_cache_dir=tmp_path / "hf",
                        workload_file=tmp_path / "prompts.jsonl",
                        llama_cpp_bin_dir=bin_dir, speed_bench_script=script)
    (tmp_path / "prompts.jsonl").write_text("x\n")
    s = AppState(settings)
    cfg = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp",
        "flags": {},
        "bench_command": [],
    }
    _rebuild_bench_command(s, cfg, "org/model")
    assert cfg["bench_command"][cfg["bench_command"].index("--bench") + 1] == "throughput_1k"
    assert "bench_error" not in cfg


def test_start_run_speed_bench_invalid_flags_rejected(client, monkeypatch):
    monkeypatch.setattr("app.api.speed_bench_deps_available", lambda: True)
    monkeypatch.setattr("app.api.resolve_speed_bench_script", lambda *a, **k: "/tmp/speed_bench.py")
    config = {
        "server_id": "llama.cpp",
        "bench_tool": "speed-bench",
        "serving_command": "llama-server -m /models/x.gguf --spec-type draft-mtp",
        "flags": {},
        "bench_flags": "--bench foo",
        "bench_command": [],
    }
    r = client.post("/api/benchmarks", json={
        "repo_id": "org/model",
        "configs": [config],
        "pause": False,
    })
    assert r.status_code == 422
    assert "unknown --bench 'foo'" in r.json()["detail"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ruben/test/llmbench/backend && .venv/bin/python -m pytest tests/test_api.py::test_rebuild_bench_command_speed_bench tests/test_api.py::test_rebuild_bench_command_speed_bench_invalid_flags tests/test_api.py::test_rebuild_bench_command_speed_bench_missing_flags_uses_default tests/test_api.py::test_start_run_speed_bench_invalid_flags_rejected -q`
Expected: FAIL — `test_rebuild_bench_command_speed_bench` asserts edited flags but the rebuild still uses the `speed_bench_osl` path; `test_rebuild_bench_command_speed_bench_invalid_flags` fails (no `bench_error` for `--bench foo`).

- [ ] **Step 3: Implement the rebuild changes**

Replace the speed-bench branch of `_rebuild_bench_command` in `backend/app/api.py` (lines 537-548) with:

```python
    if cfg.get("bench_tool") == "speed-bench":
        bin_dir = str(s.settings.llama_cpp_bin_dir) if s.settings.llama_cpp_bin_dir else None
        cfg["server_command"] = build_server_command(cfg.get("serving_command", ""), bin_dir)
        script = resolve_speed_bench_script(bin_dir, configured=s.settings.speed_bench_script)
        if not (script and speed_bench_deps_available()):
            cfg["bench_command"] = []
            cfg["bench_error"] = _speed_bench_error(script)
            return
        flags_text = cfg.get("bench_flags") or speed_bench_default_flags(s.settings.speed_bench_osl)
        flags = parse_speed_bench_flags(flags_text)
        error = validate_speed_bench_flags(flags)
        if error:
            cfg["bench_command"] = []
            cfg["bench_error"] = error
            return
        cfg["bench_command"] = build_speed_bench_command(
            script, flags, output=str(s.settings.data_dir / "speed-bench.json"))
        return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ruben/test/llmbench/backend && .venv/bin/python -m pytest tests/test_api.py -q`
Expected: PASS (53 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/ruben/test/llmbench && git add backend/app/api.py backend/tests/test_api.py && git commit -m "feat: validate edited speed-bench flags at run start"
```

---

### Task 4: Frontend — bench_flags type, textarea, and run-payload round-trip

**Files:**
- Modify: `frontend/src/api/client.ts` (line 114 area)
- Modify: `frontend/src/components/ConfigBank.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/ConfigBank.test.tsx`, `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the failing frontend tests**

Append to `frontend/src/components/ConfigBank.test.tsx`:

```tsx
test("renders and edits a SPEED-BENCH FLAGS textarea for speed-bench configs", () => {
  const onEditFlags = vi.fn();
  const configs: ConfigRow[] = [
    {
      flags: {},
      serving_command: "llama-server --spec-type draft-mtp",
      bench_tool: "speed-bench",
      bench_flags: "--bench throughput_1k --category all --limit 1 --osl 128",
    },
  ];
  render(
    <ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} onEditFlags={onEditFlags} />,
  );
  const textarea = screen.getByDisplayValue("--bench throughput_1k --category all --limit 1 --osl 128");
  fireEvent.change(textarea, { target: { value: "--bench qualitative --category coding" } });
  expect(onEditFlags).toHaveBeenCalledWith(0, "--bench qualitative --category coding");
});

test("does not render the flags textarea for non-speed-bench configs", () => {
  const configs: ConfigRow[] = [{ flags: {}, serving_command: "vllm serve m", bench_tool: "llama-bench" }];
  render(<ConfigBank n={1} onNChange={() => {}} onGenerate={() => {}} configs={configs} />);
  expect(screen.queryByDisplayValue(/--bench/)).not.toBeInTheDocument();
});
```

Append to `frontend/src/App.test.tsx`:

```tsx
test("run payload round-trips edited bench_flags", async () => {
  const { api } = await import("./api/client");
  const startSpy = vi.spyOn(api, "startBenchmark").mockResolvedValue({ run_id: 1 });
  vi.mocked(api.generateConfigs).mockResolvedValue({
    configs: [
      { flags: {}, serving_command: "llama-server --spec-type draft-mtp", bench_command: [], bench_tool: "speed-bench", bench_flags: "--bench throughput_1k --category all --limit 1 --osl 128", fit: null },
    ],
  });

  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );

  const input = await screen.findByPlaceholderText(/model/i);
  fireEvent.change(input, { target: { value: "org/model" } });
  fireEvent.click(screen.getByText(/analyze/i));
  await screen.findByText(/org\/model/i);
  fireEvent.click(screen.getByText(/generate/i));
  await screen.findByText(/llama-server --spec-type/i);

  const textarea = screen.getByDisplayValue("--bench throughput_1k --category all --limit 1 --osl 128");
  fireEvent.change(textarea, { target: { value: "--bench qualitative --category coding" } });

  fireEvent.click(screen.getByText(/run benchmark/i));
  await waitFor(() => expect(startSpy).toHaveBeenCalled());
  const body = startSpy.mock.calls[0][0] as { configs: Array<{ bench_flags?: string }> };
  expect(body.configs[0].bench_flags).toBe("--bench qualitative --category coding");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/ruben/test/llmbench/frontend && npx vitest run src/components/ConfigBank.test.tsx src/App.test.tsx`
Expected: FAIL — `onEditFlags` is not a known prop / no `bench_flags` on the response type.

- [ ] **Step 3: Implement the frontend changes**

In `frontend/src/api/client.ts`, add `bench_flags?: string;` after `bench_tool?: string;` (line 114):

```ts
      configs: Array<{
        flags: Record<string, string>;
        serving_command: string;
        bench_command: string[];
        bench_tool?: string;
        bench_flags?: string;
        fit: ConfigFit | null;
      }>;
```

In `frontend/src/components/ConfigBank.tsx`:
- Add to `ConfigRow`:
```ts
  bench_flags?: string;
```
- Add to `Props`:
```ts
  onEditFlags?: (index: number, flags: string) => void;
```
- Update the destructure:
```ts
export function ConfigBank({ n, onNChange, onGenerate, configs, onEdit, onEditFlags }: Props) {
```
- Replace the row body (the `<span className="config-index">...` through the `{cfg.fit && ...}` line, lines 37-58) with:

```tsx
          <span className="config-index">▸ {i + 1}</span>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
            <textarea
              value={cfg.serving_command}
              onChange={(e) => onEdit?.(i, e.target.value)}
              rows={2}
              style={{ fontFamily: "var(--font-mono)" }}
            />
            {cfg.bench_tool === "speed-bench" && (
              <>
                <label style={{ color: "var(--anode)", fontSize: 11, letterSpacing: 1 }}>
                  SPEED-BENCH FLAGS
                </label>
                <textarea
                  value={cfg.bench_flags ?? ""}
                  onChange={(e) => onEditFlags?.(i, e.target.value)}
                  rows={2}
                  style={{ fontFamily: "var(--font-mono)" }}
                />
              </>
            )}
          </div>
          {cfg.bench_tool === "speed-bench" && (
            <span
              style={{
                fontSize: 10,
                letterSpacing: 1,
                color: "var(--accent)",
                border: "1px solid var(--hairline)",
                padding: "2px 6px",
                whiteSpace: "nowrap",
              }}
            >
              SPEED-BENCH
            </span>
          )}
          {cfg.fit && <FitBadge fit={cfg.fit} />}
```

In `frontend/src/App.tsx`:
- Add `bench_flags: c.bench_flags,` to the run payload map (after `bench_tool: c.bench_tool,` at line 251).
- Add an `onEditFlags` prop to `<ConfigBank>` (next to `onEdit` at line 354):
```tsx
                onEditFlags={(i, flags) =>
                  setConfigs((prev) => prev.map((c, j) => (j === i ? { ...c, bench_flags: flags } : c)))
                }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/ruben/test/llmbench/frontend && npx tsc -b && npx vitest run`
Expected: PASS — tsc clean, vitest 81 passing.

- [ ] **Step 5: Commit**

```bash
cd /home/ruben/test/llmbench && git add frontend/src/api/client.ts frontend/src/components/ConfigBank.tsx frontend/src/App.tsx frontend/src/components/ConfigBank.test.tsx frontend/src/App.test.tsx && git commit -m "feat: editable speed-bench flags in the config bank"
```

---

### Task 5: Full verification

- [ ] **Step 1: Run the full backend suite**

Run: `cd /home/ruben/test/llmbench/backend && .venv/bin/python -m pytest -q`
Expected: PASS (226 tests).

- [ ] **Step 2: Run tsc and vitest**

Run: `cd /home/ruben/test/llmbench/frontend && npx tsc -b && npx vitest run`
Expected: PASS.

- [ ] **Step 3: Run Playwright e2e (requires free ports)**

Run: `cd /home/ruben/test/llmbench && ./down.sh && cd frontend && npx playwright test && cd .. && ./up.sh`
Expected: PASS (4 e2e tests). `./up.sh` restarts the dev servers in the background.

- [ ] **Step 4: Manual smoke — edit flags and see the 422**

With the backend running (`./up.sh`), POST an edited `bench_flags` with an invalid value and confirm the 422 detail:

Run: `curl -s -X POST http://localhost:8000/api/benchmarks -H "Content-Type: application/json" -d '{"repo_id":"org/model","configs":[{"server_id":"llama.cpp","bench_tool":"speed-bench","serving_command":"llama-server -m x.gguf --spec-type draft-mtp","flags":{},"bench_flags":"--bench foo","bench_command":[]}],"pause":false}'`
Expected: HTTP 422 with `{"detail":"unknown --bench 'foo'; available benches: qualitative, throughput_1k, throughput_2k, throughput_8k, throughput_16k, throughput_32k"}`

- [ ] **Step 5: Commit any remaining docs**

```bash
cd /home/ruben/test/llmbench && git add docs/superpowers/plans/2026-08-07-editable-speed-bench-flags.md && git commit -m "docs: editable speed-bench flags implementation plan"
```
