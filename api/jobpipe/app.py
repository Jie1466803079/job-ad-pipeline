"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from jobpipe import db, repo
from jobpipe.configfiles import load_companies, load_filters, load_prices, load_profile
from jobpipe.llm.base import Extractor
from jobpipe.llm.factory import make_extractor
from jobpipe.routes import machine
from jobpipe.settings import Settings


def create_app(settings: Settings | None = None, extractor: Extractor | None = None) -> FastAPI:
    settings = settings or Settings()
    if not settings.machine_api_key:
        raise RuntimeError("MACHINE_API_KEY is not set")
    config = settings.config_path

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with db.connect(settings.database_url) as conn:
            db.migrate(conn)
            repo.sync_companies(conn, load_companies(config / "companies.yaml"))
            conn.commit()
        yield

    app = FastAPI(title="job-ad-pipeline intake-api", lifespan=lifespan)
    app.state.settings = settings
    app.state.extractor = extractor or make_extractor(settings)
    app.state.filters = load_filters(config / "filters.yaml")
    app.state.profile = load_profile(config / "profile.yaml")
    app.state.prices = load_prices(config / "prices.yaml")
    app.include_router(machine.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
