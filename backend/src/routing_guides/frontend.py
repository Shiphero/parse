"""Serve the production UI from the API origin; local Vite remains independent."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, directory: Path = Path('/app/static')):
    # Register last: /api, /docs and /openapi.json must retain their own routing.
    # The UI uses hash routing, so no wildcard HTML fallback is necessary.
    if (directory / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=directory, html=True), name='frontend')
