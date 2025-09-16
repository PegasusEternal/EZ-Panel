"""Gunicorn configuration for running EZ-Panel in production.

All values can be overridden with environment variables prefixed with GUNICORN_.
The defaults aim for a reasonable balance for IO-bound Flask apps.
"""

import multiprocessing
import os

# Network binding (host:port). Override with GUNICORN_BIND.
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:5000")

# Worker processes: typical rule of thumb is (CPU * 2 + 1).
workers = int(os.getenv("GUNICORN_WORKERS", str(multiprocessing.cpu_count() * 2 + 1)))

# Threads per worker; Flask generally benefits more from workers than threads.
threads = int(os.getenv("GUNICORN_THREADS", "2"))

# Timeouts (seconds). Increase if doing long-running tasks in requests (not recommended).
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))

# Logging: '-' means stdout/stderr.
accesslog = os.getenv("GUNICORN_ACCESSLOG", "-")
errorlog = os.getenv("GUNICORN_ERRORLOG", "-")
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")

# When behind a reverse proxy (nginx, etc.), allow forwarded headers.
forwarded_allow_ips = "*"
