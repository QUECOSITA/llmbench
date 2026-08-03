<!-- SEED: established with the user before implementation; re-run /impeccable document once there's code to capture the actual tokens and components. -->
---
name: LLM Bench
description: Local benchmark instrument for LLM serving configs, ranked by decode tokens/sec.
---

# Design System: LLM Bench

## Overview

**Creative North Star: "The Lab Counter"**

LLM Bench is a laboratory instrument for measuring how fast an LLM can be served. The benchmark is a physical counter on a blackened-steel bench: the visitor feeds a model, reads the model's intended serving program and flags off its own README, builds an editable bank of configs, and watches the digits. Quantities are the interface — PROMPT PROC t/s and DECODE STAGE t/s own tube banks, and the best config's digit glows neon orange, the only warm accent on the panel.

The layout refuses the dark-GPU-dashboard rut of heavy nested cards: panels are flat, hairline-ruled, and numbered (01 MODEL INPUT → 02 CONFIG BANK → 03 RUN → 04 METRICS → 05 RESULTS — RANKED). Flow stays linear and obvious — a clear journey through the instrument — with the lab-counter material keeping it disciplined rather than chunky.

**Key Characteristics:**
- Quantities are the interface; metrics own fixed digit positions.
- Flat surfaces, hairline rules, engraved caps — no heavy cards, no shadows.
- One neon-orange accent, reserved for the lit digit and active state.
- Engineered-monospace numerals; small letter-spaced caps for labels.
- Motion is mechanical: single cross-fades for digit changes, a progress relay, no scattered hover effects.

## Colors

Neutral steel palette with a single warm accent. `[Exact tokens to be resolved during implementation.]`

### Primary
- **Neon Lit Digit** (`[to be resolved]`, ~`#FF7A00`): The only warm color. Reserved for the active state, the RUN BENCHMARK action, and the lit DECODE STAGE digits — including the winning row in the ranked results.

### Neutral
- **Blackened Steel** (`[to be resolved]`, `#16130f` family): panel ground.
- **Raised Panel** (`[to be resolved]`, `#1e1b17` family): inset banks for metric digits and config rows.
- **Hairline Rule** (`[to be resolved]`, `#3a342b` / `#4a443a`): all borders and dividers.
- **Anode Mesh Gray** (`[to be resolved]`, `#8a8478`): secondary text, engraved caps.
- **Tube Face** (`[to be resolved]`, `#d8d2c8`): primary numerals and text.

### Named Rules
**The One-Lit-Digit Rule.** The orange accent is reserved for a single point of truth at a time — the live DECODE STAGE value or the winning ranked row. It is never scattered across the panel.

## Typography

**Display/Headline/Title Font:** engineered monospace stack `[to be resolved during implementation]` for numerals and structure.
**Body Font:** `[to be resolved]` for the few prose passages.
**Label Font:** the same monospace family in small, letter-spaced, uppercase caps.

**Character:** laboratory panel readout — numerals are the loudest voice; labels whisper in engraved caps.

### Hierarchy
- **Metric Digit** (large, monospace, tracked): the t/s tube banks — the loudest element on any panel.
- **Panel Cap** (small, `[to be resolved]` size, `[to be resolved]` letter-spacing, uppercase): "01 · MODEL INPUT" section headers.
- **Body** (monospace, small): config commands, table content.
- **Hardware Line** (small caps, dim): the header spec line (RTX 4090 · 24GB VRAM · 64GB RAM · x86_64).

## Layout

A single-page stacked instrument: persistent header bar, then numbered panels in fixed order, then the Downloaded strip. `[Exact spacing scale to be resolved during implementation.]` Responsive: metric banks collapse to essential digits on small screens; panels stack full-width. The dedicated `/results` section reuses the same panel language for the full ranked history.

## Elevation & Depth

Flat by default. Depth is conveyed by tonal layering — raised panels (`#1e1b17`) sit on the steel ground (`#16130f`) inside hairline rules — never by shadows. `[Confirm no shadow vocabulary during implementation.]`

### Named Rules
**The Flat-By-Default Rule.** Surfaces are flat at rest. The only "elevation" is the panel-vs-ground tonal step; nothing casts a shadow.

## Shapes

Hairline rectangular panels with minimal radius (`[to be resolved]`, ~`4px`). Corners are tight and mechanical, consistent with the instrument chassis. `[Exact corner language to be resolved during implementation.]`

## Do's and Don'ts

### Do:
- **Do** reserve the orange accent for one lit figure at a time (live metric or winning ranked row).
- **Do** keep the workflow linear and numbered: 01 → 02 → 03 → 04 → 05.
- **Do** render all numeric metrics in engineered monospace numerals.
- **Do** label sections with small letter-spaced uppercase caps.
- **Do** use hairline rules and flat panels — never heavy cards.

### Don't:
- **Don't** use a dark-GPU-dashboard look: no neon glow edges, no thick gradient cards, no glassmorphism.
- **Don't** scatter the accent color across buttons, links, and highlights.
- **Don't** animate digits with bouncy easing — cross-fade only.
- **Don't** hide the current step; the active panel is always visibly marked.
