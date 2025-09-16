"""CLI entrypoint to launch the Flask development server.

Usage
-----
This is a convenience wrapper around app.run for local/dev environments.
For production, prefer Gunicorn with the WSGI entrypoint (ez_panel.wsgi:app).

Environment variables:
    - EZ_PANEL_HOST: bind host (default 0.0.0.0)
    - EZ_PANEL_PORT: bind port (default 5000)
    - EZ_PANEL_TLS_CERT / EZ_PANEL_TLS_KEY: optional TLS cert/key paths
"""

import argparse
import os
from .app import app
import ssl

def main():
    parser = argparse.ArgumentParser(description="Launch EZ-Panel Dashboard")
    parser.add_argument("--host", default=os.getenv("EZ_PANEL_HOST", "0.0.0.0"), help="Host to bind the server")
    parser.add_argument("--port", type=int, default=int(os.getenv("EZ_PANEL_PORT", "5000")), help="Port to run the server on")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    cert_path = os.getenv("EZ_PANEL_TLS_CERT")
    key_path = os.getenv("EZ_PANEL_TLS_KEY")
    ssl_ctx = None
    if cert_path and key_path and os.path.exists(cert_path) and os.path.exists(key_path):
        try:
            ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
            print(f"� TLS enabled (cert={cert_path})")
        except Exception as e:
            print(f"[WARN] Failed to enable TLS: {e}")
            ssl_ctx = None

    scheme = 'https' if ssl_ctx else 'http'
    print(f"🚀 Launching EZ-Panel on {scheme}://{args.host}:{args.port} (debug={args.debug})")
    app.run(host=args.host, port=args.port, debug=args.debug, ssl_context=ssl_ctx)
