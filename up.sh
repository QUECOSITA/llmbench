#!/bin/bash
# Resolve llama.cpp (llama-bench + llama-server) before starting the app; the
# sourced helper exports LLMBENCH_LLAMA_CPP_BIN_DIR and aborts if cancelled.
source "$(dirname "$0")/scripts/ensure-llama-cpp.sh"
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pip install -e '.[speed-bench]' || echo "warning: speed-bench dependencies not installed; speed-bench unavailable (app still runs)."
nohup uvicorn app.main:app --port 8000 &
cd ..
cd frontend 
nohup npm install && npm run dev &
sleep 2

clear

echo "Backend and Frontend running..."
echo "Open http://localhost:5173."
