"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from jobpipe import db, repo
from jobpipe.configfiles import load_companies, load_filters, load_prices, load_profile
from jobpipe.llm.base import Extractor
from jobpipe.llm.factory import make_extractor
from jobpipe.routes import auth, machine
from jobpipe.settings import Settings

SESSION_COOKIE = "jobpipe_session"
SESSION_MAX_AGE = 7 * 24 * 60 * 60  # a week, in seconds


def create_app(settings: Settings | None = None, extractor: Extractor | None = None) -> FastAPI:
    settings = settings or Settings()
    if not settings.machine_api_key:
        raise RuntimeError("MACHINE_API_KEY is not set")
    if not settings.session_secret or len(settings.session_secret) < 32:
        raise RuntimeError("SESSION_SECRET must be a random string of at least 32 characters")
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
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, session_cookie=SESSION_COOKIE,
                       max_age=SESSION_MAX_AGE, same_site="strict", https_only=settings.session_cookie_secure)
    app.include_router(machine.router)
    app.include_router(auth.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app
