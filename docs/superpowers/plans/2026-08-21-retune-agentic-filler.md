# Plan — Retune agentic bench: one-time 50%-ctx filler + bounded thinking

Date: 2026-08-21

## Problem

The `2026-08-20` agentic ctx-tier work ("inject 2× the tier's context as filler
plus heavy per-step thinking") overshot. Current state in `backend/app/agentic.py`:

| Tier | ctx_size | max_tokens | fill_tokens (2×) |
|------|----------|-----------|------------------|
| low | 16384 | 4096 | 32768 |
| medium | 65536 | 8192 | 131072 |
| heavy | 131072 | 65728 | 262144 |

Three issues:

1. **Filler > ctx on medium/heavy** — the injected prefill alone exceeds the
   context window, so runs fail with `context_overflow` before decode even
   starts (classifier at `benchmark.py:222`). The heavy tier is effectively
   unusable.
2. **Filler re-prefilled every step** — the whole filler sits in the system
   prompt (`agentic.py:307-308`) and is re-sent on every model call, multiplying
   prefill cost by the step count (~10 steps).
3. **Unbounded heavy thinking** — "very long, exhaustive trace" combined with a
   65728 `max_tokens` cap allows runaway generations and inflates per-step
   decode time.

## Design decisions (user-confirmed)

1. **Filler injection → one-time context message** (a `user` role message added
   once), not stuffed into every system prompt.
2. **Filler size → 50% of ctx** (`fill_tokens = ctx_size // 2`), leaving headroom
   for transcript + thinking + decode so runs complete and produce a usable t/s.
3. **Thinking → fixed target tokens per tier** (bounded decode).

## New tier table

| Tier | ctx_size | max_tokens | fill_tokens (50%) | thinking target |
|------|----------|-----------|-------------------|-----------------|
| low | 16384 | 4096 | 8192 | ~80 tok/step |
| medium | 65536 | 8192 | 32768 | ~160 tok/step |
| heavy | 131072 | 65728 | 65536 | ~320 tok/step |

Medium/heavy still inject a large one-time prefill (32K/64K tokens) — genuinely
heavy — but now fit within the context window, so runs are not *guaranteed* to
overflow.

## File map

| File | Change |
|---|---|
| `backend/app/agentic.py` | Tier table fill → ctx//2; replace `AGENTIC_THINKING` with `AGENTIC_THINKING_TOKENS`; inject filler once as a user message instead of into system prompt |
| `backend/tests/test_agentic.py` | Update the filler/thinking test; add a fill==ctx//2 assertion |
| `backend/app/benchmark.py` | Failure-classifier copy tweak (filler wording stays accurate); no logic change |
| `backend/tests/test_benchmark.py` | Verify still green (no numeric tier pins to change) |
| `backend/tests/test_servers.py` | Verify still green (cap/flag tests unchanged) |
| `backend/tests/test_api.py` | Verify still green (ctx-size/flag pins unchanged) |
| `README.md` | Update agentic paragraph (line 146): 2× filler → 50% one-time, bounded thinking |
| `docs/superpowers/specs/2026-08-20-agentic-interactive-ctx-tiers-design.md` | Update "2× filler + heavy thinking" wording + `fill_tokens=2*ctx` (line 62) |
| `docs/superpowers/plans/2026-08-20-agentic-interactive-ctx-tiers.md` | Add a retune note (kept for history) |

---

## Task 1 — `agentic.py`: tier table + one-time filler + bounded thinking (TDD)

**Files:** `backend/app/agentic.py`, `backend/tests/test_agentic.py`

- [ ] **Step 1: Write the failing tests**

Replace `test_run_agent_session_injects_filler_and_thinking` (currently
`test_agentic.py:226-248`) with two tests asserting: (a) the filler is a
one-time `user` message, not in the system prompt, and is not re-sent on later
steps; (b) each tier's `fill_tokens == ctx_size // 2`.

```python
@pytest.mark.asyncio
async def test_run_agent_session_injects_filler_once_and_thinking(monkeypatch):
    monkeypatch.setattr("app.agentic.time.monotonic", FakeClock())
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("tool_choice") == "required":
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("submit_plan", {"steps": ["a"]})]}
        else:
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [_tool_call("finish", {"answer": "ok"})]}
        return httpx.Response(200, json=_resp(msg))

    transport = httpx.MockTransport(handler)
    await run_agent_session(
        base_url="http://127.0.0.1:9", model="m", steps=3, max_tokens=4096,
        task="codebase_refactor", transport=transport, tier="heavy",
        fill_tokens=65536)  # heavy ctx 131072 // 2
    first = requests[0]["messages"]
    sys_prompt = first[0]["content"]
    # Filler is a one-time user message, NOT the system prompt.
    assert "synthetic filler" not in sys_prompt
    assert any("synthetic filler" in m.get("content", "")
               for m in first if m["role"] == "user")
    # Bounded heavy thinking target present in the system prompt.
    assert "~320 tokens" in sys_prompt
    # Filler sent once on step 1, not re-injected on later steps.
    def filler_chars(body):
        return sum(len(m.get("content", "")) for m in body["messages"]
                   if "synthetic filler" in m.get("content", ""))
    assert filler_chars(requests[0]) > 100000
    assert filler_chars(requests[1]) < 5000


def test_fill_tokens_half_ctx():
    from app.agentic import AGENTIC_TIERS
    for tier, spec in AGENTIC_TIERS.items():
        assert spec["fill_tokens"] == spec["ctx_size"] // 2
```

- [ ] **Step 2: Run** `cd backend && python -m pytest tests/test_agentic.py -v`
  → expect FAIL (filler still in system prompt; no `~320 tokens` string; no
  `fill_tokens == ctx//2`).

- [ ] **Step 3: Implement**

In `backend/app/agentic.py`:

1. Replace `AGENTIC_TIERS` fill values with `ctx_size // 2`:

```python
AGENTIC_TIERS = {
    "low": {"ctx_size": 16384, "max_tokens": 4096, "fill_tokens": 16384 // 2},
    "medium": {"ctx_size": 65536, "max_tokens": 8192, "fill_tokens": 65536 // 2},
    "heavy": {"ctx_size": 131072, "max_tokens": 65728, "fill_tokens": 131072 // 2},
}
```

2. Replace `AGENTIC_THINKING` with bounded per-tier targets:

```python
AGENTIC_THINKING_TOKENS = {
    "low": "Keep your reasoning concise, ~80 tokens per step.",
    "medium": "Provide a step-by-step reasoning trace of ~160 tokens per step.",
    "heavy": ("Produce an exhaustive reasoning trace of ~320 tokens per step, "
              "spelling out every consideration before each tool call."),
}
```

3. In `run_agent_session` (`agentic.py:303-312`), build the messages so the
   filler is injected once as a `user` message rather than into the system
   prompt:

```python
scenario = AGENTIC_TASKS.get(task, AGENTIC_TASKS["codebase_refactor"])
corpus = scenario["corpus"]
thinking = AGENTIC_THINKING_TOKENS.get(tier, AGENTIC_THINKING_TOKENS["medium"])
system_prompt = AGENTIC_SYSTEM_PROMPT + "\n" + thinking
messages = [{"role": "system", "content": system_prompt}]
if fill_tokens:
    messages.append({"role": "user", "content": _build_filler(fill_tokens)})
messages.append({"role": "user", "content": scenario["prompt"]})
```

4. Remove the old `if fill_tokens: system_prompt += ...` block and the now-unused
   `AGENTIC_THINKING` dict.

- [ ] **Step 4: Run** `cd backend && python -m pytest tests/test_agentic.py -v`
  → expect PASS.

- [ ] **Step 5: Commit**
  `git add backend/app/agentic.py backend/tests/test_agentic.py && git commit -m "feat: one-time 50% ctx filler + bounded thinking in agentic bench"`

---

## Task 2 — `benchmark.py`: failure-classifier copy

**Files:** `backend/app/benchmark.py`

- [ ] **Step 1:** The classifier messages at `benchmark.py:218-228` still reference
  "tier filler + ctx-size" / "injected filler + --ctx-size" — still accurate
  (filler is still injected). Light-touch wording update so the "raise
  --ctx-size" advice stays correct for the new 50% sizing. No logic change.
- [ ] **Step 2:** Run `cd backend && python -m pytest tests/test_benchmark.py -v`
  → PASS.
- [ ] **Step 3: Commit**
  `git add backend/app/benchmark.py && git commit -m "docs: clarify agentic failure copy for 50% filler"`

---

## Task 3 — Docs

**Files:** `README.md`, `docs/superpowers/specs/2026-08-20-agentic-interactive-ctx-tiers-design.md`, `docs/superpowers/plans/2026-08-20-agentic-interactive-ctx-tiers.md`, `docs/superpowers/plans/2026-08-21-retune-agentic-filler.md`

- [ ] **Step 1:** `README.md:146` — change "injects 2× the tier's context as
  filler plus heavy thinking" to "injects a one-time context filler (50% of the
  tier's ctx) plus tier-bounded thinking, so prefill and decode are heavy but
  runs complete without guaranteed overflow."
- [ ] **Step 2:** Design spec `2026-08-20` — update the "Inject 2×…" decision rows
  and the Architecture diagram `fill_tokens=2*ctx` (`spec line 62`) and
  "inject filler + thinking into system prompt" (`spec line 66`) to the one-time
  50% approach.
- [ ] **Step 3:** Add a retune note to the `2026-08-20` plan (kept for history).
- [ ] **Step 4: Commit**
  `git add README.md docs/ && git commit -m "docs: document retuned one-time 50% agentic filler"`

---

## Task 4 — Full local verification (per AGENTS.md)

- [ ] Backend: `cd backend && python -m pytest`
- [ ] Frontend typecheck + unit: `cd frontend && npx tsc -b && npx vitest run`
- [ ] E2E: `cd frontend && npx playwright test`
- [ ] Review: `git status` and `git diff main` — only intended files.

## Notes

- `--max-tokens` cap (65728) is **unchanged** — it is only the validation
  ceiling; the per-tier `max_tokens` default is independent of filler.
- Frontend is untouched — the tier dropdown, flags, and ctx-size wiring don't
  change; only backend filler/thinking internals change.
- Heavy `64K fill + 65K max_tokens ≈ 131K ctx` is right at the edge; a model
  filling the whole `max_tokens` could still overflow, which the classifier
  catches, but overflow is no longer unconditional.
- No DB migration needed — filler/thinking are not persisted.
