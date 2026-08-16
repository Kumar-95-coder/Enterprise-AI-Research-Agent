#!/usr/bin/env bash
# Convenience script: fresh local setup + a first real research job, end to end.
set -e
cd "$(dirname "$0")/../backend"

echo "==> Installing dependencies"
pip install -r requirements.txt --break-system-packages -q
python3 -m spacy download en_core_web_sm 2>/dev/null || \
  pip install --break-system-packages -q \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

echo "==> Applying database migrations"
rm -f research_agent.db
alembic upgrade head

echo "==> Running tests"
pytest tests/ -q

echo "==> Starting server"
uvicorn app.main:app --port 8000 &
SERVER_PID=$!
sleep 3

echo "==> Submitting a real research job"
JOB_ID=$(curl -s -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"question": "What AI technologies are changing manufacturing?"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "    job id: $JOB_ID"
sleep 8
curl -s "http://localhost:8000/api/research/$JOB_ID" | python3 -m json.tool

echo ""
echo "Server running at http://localhost:8000 (PID $SERVER_PID). Ctrl+C to stop, or:"
echo "  kill $SERVER_PID"
wait $SERVER_PID
