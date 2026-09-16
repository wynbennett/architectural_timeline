"""Vercel Python entrypoint. Vercel looks for a WSGI `app` in api/index.py."""
from app import create_app

app = create_app()
