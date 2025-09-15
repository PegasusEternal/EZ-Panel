# create the file in the project root
cat > /workspaces/codespaces-blank/c2_proto/check_env.sh <<'SH'
# filepath: /workspaces/codespaces-blank/c2_proto/check_env.sh
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "=== 1) show top of setup.py and requirements.txt ==="
echo "---- setup.py ----"
sed -n '1,200p' setup.py || true
echo "---- requirements.txt ----"
sed -n '1,200p' requirements.txt || true

echo
echo "=== 2) list relevant files ==="
find . -type f \( -name "*.py" -o -name "*.js" -o -name "*.html" -o -name "*.css" \) -not -path "./venv/*" -not -path "./.git/*" -print

echo
echo "=== 3) duplicates of key assets ==="
find . -type f -name "xterm.js" -o -name "xterm.css" -o -name "dashboard.html" -print || true

echo
echo "=== 4) create venv (if missing) and install ==="
PYTHON_CANDIDATES=(python3.12 python3.11 python3.10 python3)
PYTHON_CMD=""
for p in "${PYTHON_CANDIDATES[@]}"; do
  if command -v "$p" >/dev/null 2>&1; then
    PYTHON_CMD="$p"
    break
  fi
done

if [ -z "$PYTHON_CMD" ]; then
  echo "No python executable found in candidates: ${PYTHON_CANDIDATES[*]}"
  exit 1
fi

echo "Using python: $PYTHON_CMD"

if [ ! -d ".venv" ]; then
  "$PYTHON_CMD" -m venv .venv || ("$PYTHON_CMD" -m venv .venv || true)
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip setuptools wheel || true

if [ -f requirements.txt ]; then
  python -m pip install -r requirements.txt || true
fi

python -m pip install -e . || true

echo
echo "=== 5) pip check and outdated ==="
python -m pip check || true
python -m pip list --outdated --format=columns || true

echo
echo "=== 6) package import & entry point info ==="
python - <<'PY'
import importlib, sys, pkgutil
try:
    import ez_panel
    print("ez_panel module:", ez_panel.__file__)
except Exception as e:
    print("Failed to import ez_panel:", e)
try:
    import pkg_resources
    try:
        dist = pkg_resources.get_distribution("EZ-Panel")
        print("Installed EZ-Panel:", dist)
        print("Entry points:")
        for ep in dist.get_entry_map().get('console_scripts', {}).values():
            print(" ", ep.name, "->", ep.module_name, ep.attrs)
    except Exception as e:
        print("pkg_resources distribution check failed:", e)
except Exception:
    print("pkg_resources not available")
PY

echo
echo "=== 7) start app briefly and curl resources ==="
python -m ez_panel.app &
PID=$!
sleep 1

echo "server pid: $PID"
curl -s -I http://127.0.0.1:5000/ || true
curl -s -I http://127.0.0.1:5000/static/js/cli.js || true
curl -s -I http://127.0.0.1:5000/static/js/xterm.js || true
curl -s -I http://127.0.0.1:5000/static/css/style.css || true
curl -sS http://127.0.0.1:5000/api/server_info || true
curl -sS http://127.0.0.1:5000/api/devices || true

kill "$PID" >/dev/null 2>&1 || true
wait "$PID" 2>/dev/null || true

echo "=== done ==="
SH

# make it executable
chmod +x /workspaces/codespaces-blank/c2_proto/check_env.sh

# run and save output to a log you can paste
cd /workspaces/codespaces-blank/c2_proto
./check_env.sh 2>&1 | tee check_env.log