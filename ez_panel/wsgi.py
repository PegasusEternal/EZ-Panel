"""WSGI entrypoint for production servers (e.g., Gunicorn).

Point Gunicorn at 'ez_panel.wsgi:app'. Configuration such as worker count,
timeouts, and logging should be supplied via gunicorn_conf.py and environment.
"""

from .app import create_app

# WSGI app object for Gunicorn and other WSGI servers
app = create_app()
