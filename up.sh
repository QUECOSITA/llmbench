#!/bin/bash
# Point llama-bench discovery at a local llama.cpp build if present.
if [ -z "${LLMBENCH_LLAMA_CPP_BIN_DIR:-}" ] && [ -d "$HOME/llama.cpp/build/bin" ]; then
    export LLMBENCH_LLAMA_CPP_BIN_DIR="$HOME/llama.cpp/build/bin"
fi
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
nohup uvicorn app.main:app --port 8000 &
cd ..
cd frontend 
nohup npm install && npm run dev &
sleep 2

clear

echo "Backend and Frontend running..."
echo "Open http://localhost:5173."