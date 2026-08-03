# LLM Bench

Benchmark Hugging Face coding LLMs across llama.cpp, vLLM, and sglang to find the best serving config by DECODE STAGE tokens/sec.

## Run

Backend: `cd backend && pip install -e '.[dev]' && uvicorn app.main:app --port 8000`
Frontend: `cd frontend && npm install && npm run dev`

Open http://localhost:5173.

## Tests

Backend: `cd backend && python -m pytest`
Frontend: `cd frontend && npx vitest run && npx playwright test`
