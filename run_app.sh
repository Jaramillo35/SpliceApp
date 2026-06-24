#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
exec /Users/martinjaramillo/miniforge3/bin/python -m streamlit run app.py --server.headless true --server.port 8501
