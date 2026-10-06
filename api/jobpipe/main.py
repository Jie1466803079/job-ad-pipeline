"""Entry point for uvicorn: `uvicorn jobpipe.main:app`."""

from jobpipe.app import create_app

app = create_app()
