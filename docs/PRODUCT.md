# Product Document

## Overview
This document defines the product specification for llmbench.

## Core Features
- Model download via HuggingFace CLI
- Benchmark configuration generation
- llama-bench / speed-bench execution
- Real-time progress broadcasting via WebSocket
- SQLite-persisted model and benchmark state

## User Flow
1. User provides a model reference (repo/file)
2. System analyzes the model card and detects serving programs
3. Configs are generated with benchmark commands
4. Benchmarks run with pause/continue support
5. Results stored in SQLite

## Configuration
- Server: llama.cpp only
- Benchmark: llama-bench (default) or speed-bench (speculative decoding)
- Hardware-aware config generation (vram/ram limits)

## API Endpoints
- /api/servers - binary detection
- /api/models/analyze - model card analysis
- /api/models/download - download initiation
- /api/configs/generate - config bank generation
- /api/benchmarks - benchmark run management

## Persistence
- SQLite database for model and benchmark tracking
- Migrations handled automatically
- Stale runs cleaned on initialization

## Deployment
- Backend: uvicorn (FastAPI)
- Frontend: Vite (real-time WebSocket UI)
- CI: pytest + vitest + Playwright e2e