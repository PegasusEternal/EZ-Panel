import os
import subprocess
import datetime
import logging
from typing import List, Dict

from flask import Flask, render_template, request, jsonify

# Try to import the project's scanner; provide a small fallback to keep server runnable
try:
    from .utils.network_scan import scan_network  # type: ignore
except Exception:

    def scan_network() -> List[Dict]:
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
    for p in candidates:
        if p and os.path.exists(p):
            return os.path.abspath(p)
    return os.path.abspath(fallback)


TEMPLATE_FOLDER = _first_existing(TEMPLATE_CANDIDATES, os.path.join(HERE, "templates"))
STATIC_FOLDER = _first_existing(STATIC_CANDIDATES, os.path.join(HERE, "static"))


# -----------------------
# App factory & creation
# -----------------------
def create_app() -> Flask:
    app = Flask(__name__, template_folder=TEMPLATE_FOLDER, static_folder=STATIC_FOLDER)

    # Basic logging
    logging.basicConfig(level=logging.INFO)
    app.logger.info("EZ-Panel starting")
    app.logger.info("template_folder=%s", TEMPLATE_FOLDER)
    app.logger.info("static_folder=%s", STATIC_FOLDER)

    # Serve dashboard template
    @app.route("/", methods=["GET"])
    def index():
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
    @app.route("/run", methods=["POST"])
    def run_command():
        payload = request.get_json(silent=True) or {}
        cmd = payload.get("command", "")
        if not isinstance(cmd, str) or not cmd.strip():
            return jsonify({"output": ""})

        app.logger.info("Executing command in Kali container: %s", cmd)
        try:
            # Execute the command inside the running Kali Linux container
            result = subprocess.run(
                ["docker", "exec", "c2panel_c2panel_1", "bash", "-c", cmd],
                capture_output=True,
                text=True,
                timeout=30,
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
    @app.route("/api/server_info", methods=["GET"])
    def server_info():
        return jsonify(
            {
                "time_utc": datetime.datetime.utcnow().isoformat() + "Z",
                "status": "running",
                "template_folder": TEMPLATE_FOLDER,
                "static_folder": STATIC_FOLDER,
            }
        )

    # Network devices endpoint (normalized output)
    @app.route("/api/devices", methods=["GET"])
    def devices():
        try:
            raw = scan_network() or []
            normalized = []
            for d in raw:
                if isinstance(d, dict):
                    normalized.append(
                        {
                            "name": d.get("name") or d.get("ip") or "unknown",
                            "ip": d.get("ip", "unknown"),
                            "status": d.get("status", "unknown"),
                            "type": d.get("type", "unknown"),
                        }
                    )
                else:
                    normalized.append(
                        {
                            "name": str(d),
                            "ip": "unknown",
                            "status": "unknown",
                            "type": "unknown",
                        }
                    )
            return jsonify({"devices": normalized})
        except Exception as exc:
            app.logger.exception("network scan failed")
            return jsonify({"devices": [], "error": str(exc)}), 500

    return app


# Create module-level app for tools that import ez_panel.app.app
app = create_app()


# -----------------------
# CLI/dev entrypoint
# -----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)