#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY=${PYTHON:-python3}

if [ ! -d .venv ]; then
  echo "[dev-venv] Creating virtualenv..."
  "$PY" -m venv .venv
fi

echo "[dev-venv] Activating and installing package (editable)..."
source .venv/bin/activate
python -m pip install -U pip wheel setuptools
pip install -e .

if [[ "${EZ_PANEL_MDNS:-0}" == "1" ]]; then
  echo "[dev-venv] Installing mDNS extra..."
  pip install 'zeroconf>=0.39'
fi

echo "[dev-venv] Done. Activate with: source .venv/bin/activate"
echo "[dev-venv] Run (safe):   EZ-Panel --host 0.0.0.0 --port 5000"
echo "[dev-venv] Or (prod):    EZ-Panel --host 0.0.0.0 --port 5000"
