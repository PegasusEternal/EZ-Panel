import argparse
from .app import app

def main():
    parser = argparse.ArgumentParser(description="Launch EZ-Panel Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=5000, help="Port to run the server on")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    print(f"🚀 Launching EZ-Panel on {args.host}:{args.port} (debug={args.debug})")
    app.run(host=args.host, port=args.port, debug=args.debug)
