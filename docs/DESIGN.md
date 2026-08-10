# Design Document

## Overview
This document describes the design decisions made for the llmbench project.

## Architecture
llmbench is a benchmarking tool that uses llama.cpp as its core server.

### Server Management
- Single server architecture: llama.cpp only
- Binary detection via filesystem scan
- Hardware detection via psutil

### Download & Sync Pipeline
1. Download models via HuggingFace CLI
2. Store artifacts in resolved gguf directory
3. Maintain model status in SQLite database

### Benchmark Engine
- llama-bench for prompt processing and decode TPS
- Speed bench for speculative decoding models
- Asynchronous runner with pause/continue interface

### API Layer
- FastAPI routes for download, config generation, and benchmark runs
- WebSocket broadcast for progress updates
- SQLite backend for persistent state

## State Management
- SQLite database for model and benchmark tracking
- SQLite migrations handled via db.py
- Stale runs cleaned on initialization

## Configuration
- Settings managed via pydantic BaseSettings
- HF cache dir, llama.cpp bin dir, workload file configurable
- Benchmark timeout and speed bench timeout configurable

## Frontend Integration
- WebSocket-based real-time progress broadcasting
- Config bank UI for generating and editing benchmark configs
- Download UI with progress and cancel support

## Testing
- Backend pytest suite
- Frontend vitest + Playwright e2e
- CI mirrors local test suite

## Deployment
- uvicorn for backend serving
- Vite for frontend dev server
- up.sh / down.sh for lifecycle management