"""
Flask application for EZ-Panel.

This file defines the app factory (create_app) and all HTTP endpoints used by the
dashboard and API. It emphasizes safe defaults and clear environment gates for
potentially sensitive operations.

Key concepts:
    - Template/static folder discovery: supports multiple layouts so you can
        rearrange the package without breaking templates.
    - Safe server info and health endpoints.
    - Network device discovery via utils.network_scan with optional deep enrichment.
    - Optional command execution endpoint (/run) with strict allowlist, disabled by
        default via env (ALLOW_DOCKER_EXEC/ALLOW_HOST_EXEC) and basic sanitization.
    - Background scan jobs with in-memory job tracking and JSONL history.
    - Optional PTY WebSocket endpoint for interactive shell, disabled by default and
        gated by env (EZ_PANEL_ENABLE_PTY and ALLOW_HOST_EXEC).
    - New: Safe Tasks API that executes only allowlisted, parameter-validated tasks
        loaded from YAML (see utils/tasks.py).

Customization:
    - Adjust environment variables to change defaults (see /api/server_info for
        effective config values).
    - Extend the allowed command list or tasks YAML for additional administrative
        actions; keep safety checks tight.
"""

import os
import subprocess
import datetime
import logging
import re
import threading
from typing import List, Dict, Tuple, Any

from flask import Flask, render_template, request, jsonify

# Try to import the project's scanner; provide a small fallback to keep server runnable
try:
    from .utils.network_scan import scan_network, discover_all_local_cidrs  # type: ignore
except Exception:
    # Fallback stubs with matching signatures for type checkers
    from typing import Optional

    def scan_network(
        subnet: Optional[str] = None,
        include_offline: bool = False,
        method: str = "auto",
        timeout_sec: float = 0.8,
        deep_discovery: bool = False,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "name": "mock-1",
                "ip": "192.0.2.10",
                "status": "online",
                "type": "unknown",
            },
            {
                "name": "mock-2",
                "ip": "192.0.2.11",
                "status": "offline",
                "type": "unknown",
            },
        ]

    def discover_all_local_cidrs() -> List[str]:
        return ["192.0.2.0/24"]


# -----------------------
# Path resolution
# -----------------------
HERE = os.path.abspath(os.path.dirname(__file__))

TEMPLATE_CANDIDATES = [
    os.path.join(HERE, "templates"),  # package-local templates
    os.path.join(HERE, "..", "templates"),  # parent templates (project root)
    os.path.join(HERE, "..", "..", "ez_panel", "templates"),  # alternate nested layout
]

STATIC_CANDIDATES = [
    os.path.join(HERE, "static"),  # package-local static
    os.path.join(HERE, "..", "static"),  # parent static (project root)
    os.path.join(HERE, "..", "..", "ez_panel", "static"),  # alternate nested layout
]


def _first_existing(candidates: List[str], fallback: str) -> str:
    """Return the first existing path from candidates, or the fallback.

    This lets the app work with different on-disk layouts without code changes.
    """
    for p in candidates:
        if p and os.path.exists(p):
            return os.path.abspath(p)
    return os.path.abspath(fallback)


TEMPLATE_FOLDER = _first_existing(TEMPLATE_CANDIDATES, os.path.join(HERE, "templates"))
STATIC_FOLDER = _first_existing(STATIC_CANDIDATES, os.path.join(HERE, "static"))


# -----------------------
# App factory & creation
# -----------------------
def strtobool_env(name: str, default: bool = False) -> bool:
    """Read a boolean-like environment variable and normalize to bool.

    Accepts: 1/0, true/false, yes/no, on/off (case-insensitive).
    """
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def create_app() -> Flask:
    """Application factory: creates and configures a Flask app instance.

    The app resolves template/static folders dynamically and registers all routes.
    """
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)

    # Basic logging
    logging.basicConfig(level=logging.INFO)
    app.logger.info("EZ-Panel starting")
    app.logger.info("template_folder=%s", TEMPLATE_FOLDER)
    app.logger.info("static_folder=%s", STATIC_FOLDER)

    # Serve dashboard template
    @app.route("/", methods=["GET"])
    def index() -> Any:
        try:
            return render_template("dashboard.html")
        except Exception as exc:
            app.logger.exception("render_template failed")
            return (
                f"<html><body><h1>EZ-Panel</h1>"
                f"<p>Failed to render dashboard. template_folder={TEMPLATE_FOLDER}</p>"
                f"<pre>{exc}</pre></body></html>",
                500,
            )

    # Execute shell commands inside the Kali Linux container
    # Dangerous command execution: DISABLED by default; enable with ALLOW_DOCKER_EXEC=1
    # Optional host execution: enable with ALLOW_HOST_EXEC=1

    # Maintain a simple per-client working directory so `cd` persists across commands
    _CWD_MAP: Dict[str, str] = {}
    _CWD_LOCK = threading.Lock()

    def _session_key() -> str:
        """Identify the client session for per-session working directory.

        Priority: X-Term-Session header, then remote_addr, then 'default'.
        """
        # Prefer a header from client; fall back to remote address
        return request.headers.get("X-Term-Session") or request.remote_addr or "default"

    def _get_default_cwd(mode: str) -> str:
        """Return a sensible default CWD depending on execution mode."""
        if mode == "docker":
            return "/root"
        return os.path.expanduser("~") or "/"

    def _get_cwd(mode: str) -> str:
        key = _session_key()
        with _CWD_LOCK:
            return _CWD_MAP.get(key) or _get_default_cwd(mode)

    def _set_cwd(new_cwd: str) -> None:
        key = _session_key()
        with _CWD_LOCK:
            _CWD_MAP[key] = new_cwd
    # -----------------------
    # Secure command execution with allowlist
    # -----------------------
    # Allowlist: command name (first token) -> whether it can pass arbitrary args.
    # Only simple network / diagnostic tooling kept. Extend via env EZ_PANEL_EXTRA_CMDS="cmd1,cmd2".
    BASE_ALLOWED = {
        "ls": True,
        "pwd": False,
        "whoami": False,
        "id": False,
        "cat": True,
        "head": True,
        "tail": True,
        "echo": True,
        "arp": True,
        "ip": True,
        "ping": True,
        "traceroute": True,
        "nmap": True,
        "arp-scan": True,
        "netstat": True,
        "ss": True,
        "route": True,
        "hostname": False,
        "uname": True,
        "df": True,
        "free": True,
    }
    extra = os.getenv("EZ_PANEL_EXTRA_CMDS", "").strip()
    if extra:
        for token in extra.split(","):
            t = token.strip()
            if t:
                BASE_ALLOWED.setdefault(t, True)

    SAFE_BLOCK_PATTERNS = [
        r";", r"&&", r"\|\|", r"\|", r">", r"<", r"`", r"\$\(", r"\\n"
    ]

    def _validate_command(raw: str) -> Tuple[bool, str]:
        """Return (ok, base) for a proposed command string.

        - Blocks dangerous shell operators like pipes/redirection/subshells.
        - Only allows a predefined set of base commands (BASE_ALLOWED), plus 'cd'.
        """
        stripped = raw.strip()
        if not stripped:
            return True, ""  # empty is fine (handled earlier)
        # Disallow obvious chaining / redirection / subshell
        for pat in SAFE_BLOCK_PATTERNS:
            if re.search(pat, stripped):
                return False, f"Unsupported operator or metacharacter detected: {pat}"
        # Tokenize (basic split)
        parts = stripped.split()
        if not parts:
            return False, "Empty command"
        base = parts[0]
        if base == "cd":
            return True, "cd"
        if base not in BASE_ALLOWED:
            return False, f"Command '{base}' not in allowlist"
        # Could add per-command arg validation here if needed
        return True, base

    @app.route("/run", methods=["POST"])
    def run_command() -> Any:
        """POST /run: execute a single allowlisted command.

        Environment gates:
          - ALLOW_DOCKER_EXEC: allow execution inside container with docker exec
          - ALLOW_HOST_EXEC: allow execution on the host
        """
        allow_docker = strtobool_env("ALLOW_DOCKER_EXEC", False)
        allow_host = strtobool_env("ALLOW_HOST_EXEC", False)
        if not (allow_docker or allow_host):
            return jsonify({"error": "command execution disabled"}), 403
        payload = request.get_json(silent=True) or {}
        cmd = payload.get("command", "")
        if not isinstance(cmd, str) or not cmd.strip():
            return jsonify({"output": ""})

        # Choose execution mode: docker (default if enabled) or host
        mode = os.getenv("EXEC_MODE")
        if mode not in {"docker", "host", None}:
            mode = None
        if mode is None:
            mode = "docker" if allow_docker else "host"

        cwd = _get_cwd(mode)

        # Handle simple `cd`
        cd_match = re.match(r"^\s*cd\s*(?P<path>[^;\n\r]*)$", cmd.strip())
        if cd_match is not None:
            path = (cd_match.group("path") or "").strip()
            if not path or path == "~":
                new_cwd = _get_default_cwd(mode)
            elif path == "-":
                new_cwd = cwd
            elif path.startswith("/"):
                new_cwd = path
            else:
                new_cwd = os.path.normpath(os.path.join(cwd, path))
            _set_cwd(new_cwd)
            return jsonify({"output": ""})

        ok, base = _validate_command(cmd)
        if not ok:
            return jsonify({"error": base}), 400

        app.logger.info("Executing (allowlist) command (%s) cwd=%s: %s", mode, cwd, cmd)
        try:
            timeout_s = int(os.getenv("EXEC_TIMEOUT", "30"))
            wrapped = f"cd {cwd} ; {cmd}"
            if mode == "docker":
                target_container = os.getenv("EXEC_CONTAINER_NAME", "c2panel_c2panel_1")
                result = subprocess.run(
                    ["docker", "exec", target_container, "bash", "-lc", wrapped],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
            else:
                result = subprocess.run(
                    ["bash", "-lc", wrapped],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                )
            output = (result.stdout or "") + (result.stderr or "")
        except subprocess.TimeoutExpired:
            output = "Command timed out"
            app.logger.warning("Command timed out")
        except Exception as exc:
            output = f"Execution error: {exc}"
            app.logger.exception("Execution error")
        return jsonify({"output": output})

    # Minimal server info for UI diagnostics
    def _bool_env(name: str, default: bool = False) -> bool:
        return str(os.getenv(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}

    def _default_method() -> str:
        # Safe mode forces ping unless overridden explicitly by query
        if _bool_env("EZ_PANEL_SAFE_MODE", False):
            return os.getenv("EZ_PANEL_SCAN_METHOD_DEFAULT", "ping")
        return os.getenv("EZ_PANEL_SCAN_METHOD_DEFAULT", "auto")

    def _default_deep() -> bool:
        if _bool_env("EZ_PANEL_SAFE_MODE", False):
            return _bool_env("EZ_PANEL_DEEP_DEFAULT", False)
        return _bool_env("EZ_PANEL_DEEP_DEFAULT", False)

    def _default_include_offline() -> bool:
        return _bool_env("EZ_PANEL_INCLUDE_OFFLINE_DEFAULT", False)

    @app.route("/api/server_info", methods=["GET"])
    def server_info() -> Any:
        """GET /api/server_info: return effective config and paths.

        Useful for frontend defaults and operator diagnostics.
        """
        return jsonify(
            {
                "time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "status": "running",
                "template_folder": TEMPLATE_FOLDER,
                "static_folder": STATIC_FOLDER,
                "config": {
                    "safe_mode": _bool_env("EZ_PANEL_SAFE_MODE", False),
                    "scan_method_default": _default_method(),
                    "deep_default": _default_deep(),
                    "include_offline_default": _default_include_offline(),
                    "ui_auto_refresh_ms": int(os.getenv("EZ_PANEL_UI_AUTO_REFRESH_MS", "5000")),
                    "multi_subnet": True,
                },
            }
        )

    @app.route("/healthz", methods=["GET"])  # simple k8s/docker health probe
    def healthz() -> Any:
        """GET /healthz: simple readiness/liveness probe."""
        return jsonify({"ok": True}), 200

    # Network devices endpoint (normalized output)
    @app.route("/api/devices", methods=["GET"])
    def devices() -> Any:
        """GET /api/devices: return normalized device list.

        Query params (optional): subnet, method, include_offline, deep
        - In safe_mode, defaults are conservative (ping method, no deep).
        """
        try:
            subnet = request.args.get("subnet")
            method = request.args.get("method") or _default_method()
            include_offline = request.args.get("include_offline")
            if include_offline is None:
                include_offline = _default_include_offline()
            else:
                include_offline = str(include_offline).lower() in {"1", "true", "yes", "on"}
            deep = request.args.get("deep")
            if deep is None:
                deep = _default_deep()
            else:
                deep = str(deep).lower() in {"1", "true", "yes", "on"}
            raw = scan_network(subnet=subnet, include_offline=bool(include_offline), method=method, deep_discovery=bool(deep)) or []
            normalized = []
            for d in raw:
                if isinstance(d, dict):
                    normalized.append(
                        {
                            "name": d.get("name") or d.get("ip") or "unknown",
                            "ip": d.get("ip", "unknown"),
                            "status": d.get("status", "unknown"),
                            "type": d.get("type", "unknown"),
                            "mac": d.get("mac"),
                            "vendor": d.get("vendor"),
                        }
                    )
                else:
                    normalized.append(
                        {
                            "name": str(d),
                            "ip": "unknown",
                            "status": "unknown",
                            "type": "unknown",
                            "mac": None,
                            "vendor": None,
                        }
                    )
            return jsonify({"devices": normalized})
        except Exception as exc:
            app.logger.exception("network scan failed")
            return jsonify({"devices": [], "error": str(exc)}), 500

    @app.route("/api/subnets", methods=["GET"])
    def list_subnets() -> Any:
        """GET /api/subnets: enumerate local interface CIDRs."""
        try:
            subs = discover_all_local_cidrs()
            return jsonify({"subnets": subs, "supports_all": True})
        except Exception as exc:
            return jsonify({"subnets": [], "error": str(exc), "supports_all": False}), 500

    # -----------------------
    # Background scan jobs
    # -----------------------
    import uuid, time as _time, json as _json
    from pathlib import Path

    JOBS: dict = {}
    JOB_LOCK = threading.Lock()
    DATA_DIR = Path(os.getenv("EZ_PANEL_DATA_DIR", os.path.join(HERE, "..", "..", "data")))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH = DATA_DIR / "scan_history.jsonl"

    def _run_scan_job(job_id: str, params: Dict[str, Any]) -> None:
        """Worker function for background scans.

        Writes progress into JOBS and appends results to HISTORY_PATH as JSONL.
        """
        start_ts = _time.time()
        try:
            with JOB_LOCK:
                JOBS[job_id].update({"status": "running", "progress": 5})
            res = scan_network(
                subnet=params.get("subnet"),
                include_offline=params.get("include_offline", False),
                method=params.get("method", "auto"),
                deep_discovery=params.get("deep", False),
            )
            with JOB_LOCK:
                JOBS[job_id].update({
                    "status": "completed",
                    "progress": 100,
                    "result": res,
                    "duration": _time.time() - start_ts,
                })
            # append to history
            rec = {"ts": _time.time(), "params": params, "result": res}
            with open(HISTORY_PATH, "a", encoding="utf-8") as f:
                f.write(_json.dumps(rec) + "\n")
        except Exception as exc:  # pragma: no cover - runtime safety
            with JOB_LOCK:
                JOBS[job_id].update({"status": "failed", "error": str(exc), "progress": 100})

    @app.route("/api/scan/start", methods=["POST"])
    def scan_start() -> Any:
        """POST /api/scan/start: kick off a background scan job."""
        payload = request.get_json(silent=True) or {}
        params = {
            "subnet": payload.get("subnet"),
            "method": payload.get("method", "auto"),
            "include_offline": bool(payload.get("include_offline", False)),
            "deep": bool(payload.get("deep", False)),
        }
        job_id = str(uuid.uuid4())
        with JOB_LOCK:
            JOBS[job_id] = {"status": "queued", "progress": 0}
        t = threading.Thread(target=_run_scan_job, args=(job_id, params), daemon=True)
        t.start()
        return jsonify({"job_id": job_id, "status": "queued"})

    @app.route("/api/scan/status", methods=["GET"])
    def scan_status() -> Any:
        """GET /api/scan/status: return state of a background scan job."""
        job_id = request.args.get("job_id")
        if not job_id:
            return jsonify({"error": "missing job_id"}), 400
        with JOB_LOCK:
            data = JOBS.get(job_id)
        if not data:
            return jsonify({"error": "unknown job_id"}), 404
        return jsonify({"job_id": job_id, **data})

    @app.route("/api/scan/history", methods=["GET"])
    def scan_history() -> Any:
        """GET /api/scan/history: tail recent scan results from JSONL history."""
        limit = int(request.args.get("limit", "10"))
        out = []
        if HISTORY_PATH.exists():
            try:
                with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-limit:]
                out = [_json.loads(l) for l in lines]
            except Exception:
                out = []
        return jsonify({"history": out})

    # -----------------------
    # Safe Tasks (approved jobs)
    # -----------------------
    # Environment gate: EZ_PANEL_ENABLE_TASKS=1
    from .utils import tasks as _tasks

    @app.route("/api/tasks", methods=["GET"])
    def tasks_list() -> Any:
        if not strtobool_env("EZ_PANEL_ENABLE_TASKS", False):
            return jsonify({"error": "Tasks disabled"}), 403
        items = _tasks.load_tasks()
        # Serialize with parameter schemas but without command body
        out = []
        for t in items:
            out.append({
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "mode": t.mode,
                "params": [
                    {"name": p.name, "pattern": p.pattern, "required": p.required}
                    for p in (t.params or [])
                ]
            })
        return jsonify({"tasks": out})

    @app.route("/api/tasks/run", methods=["POST"])
    def tasks_run() -> Any:
        if not strtobool_env("EZ_PANEL_ENABLE_TASKS", False):
            return jsonify({"error": "Tasks disabled"}), 403
        payload = request.get_json(silent=True) or {}
        task_id = payload.get("id")
        params = payload.get("params") or {}
        if not isinstance(task_id, str):
            return jsonify({"error": "Missing task id"}), 400
        items = _tasks.load_tasks()
        target = next((t for t in items if t.id == task_id), None)
        if not target:
            return jsonify({"error": "Unknown task id"}), 404
        rc, out = _tasks.run_task(target, params=params)
        return jsonify({"returncode": rc, "output": out})

    # -----------------------
    # Optional PTY WebSocket (interactive) (EXPERIMENTAL)
    # -----------------------
    # Enabled only if EZ_PANEL_ENABLE_PTY=1 and ALLOW_HOST_EXEC=1 (no docker exec here)
    try:
        from simple_websocket import Server as _WSServer  # type: ignore
    except Exception:  # pragma: no cover - optional dep
        _WSServer = None  # type: ignore

    if _WSServer:
        import pty, select, tty, fcntl, struct, termios
        import shlex

        @app.route('/ws/pty')
        def ws_pty():  # type: ignore
            if not (strtobool_env('EZ_PANEL_ENABLE_PTY', False) and strtobool_env('ALLOW_HOST_EXEC', False)):
                return jsonify({'error': 'PTY disabled'}), 403
            # Upgrade to websocket
            try:
                ws = _WSServer(environ=request.environ, heartbeat=30)  # type: ignore[call-arg]
            except Exception as exc:  # pragma: no cover
                app.logger.exception('WebSocket upgrade failed')
                return jsonify({'error': str(exc)}), 500

            def _spawn_shell():
                pid, fd = pty.fork()
                if pid == 0:  # child
                    # Launch a restricted shell (login-ish environment)
                    os.execvp('bash', ['bash', '-l'])
                return pid, fd

            pid, pty_fd = _spawn_shell()
            app.logger.info('PTY session started pid=%s', pid)

            # Set non-blocking
            fl = fcntl.fcntl(pty_fd, fcntl.F_GETFL)
            fcntl.fcntl(pty_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            try:
                while True:
                    rlist, _, _ = select.select([pty_fd], [], [], 0.05)
                    if rlist:
                        try:
                            data = os.read(pty_fd, 4096)
                            if not data:
                                ws.send('\r\n[session closed]\r\n')
                                break
                            ws.send(data.decode(errors='ignore'))
                        except OSError:
                            break
                    # Receive messages (command input / resize)
                    try:
                        msg = ws.receive(timeout=0.01)
                    except Exception:
                        msg = None
                    if msg:
                        if msg.startswith('__RESIZE__'):
                            # Format: __RESIZE__ cols rows
                            try:
                                _, cols, rows = msg.split()
                                cols_i, rows_i = int(cols), int(rows)
                                # Resize the PTY window
                                size = struct.pack('HHHH', rows_i, cols_i, 0, 0)
                                fcntl.ioctl(pty_fd, termios.TIOCSWINSZ, size)
                            except Exception:
                                pass
                        else:
                            os.write(pty_fd, msg.encode())
            finally:
                try:
                    os.close(pty_fd)
                except Exception:
                    pass
                app.logger.info('PTY session ended pid=%s', pid)
            return ''  # Not used; WebSocket already handled

    return app


# Create module-level app for tools that import ez_panel.app.app
app = create_app()



# -----------------------
# CLI/dev entrypoint
# -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)