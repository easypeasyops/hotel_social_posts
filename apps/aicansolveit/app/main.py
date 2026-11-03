from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.assets.public_router import router as public_upload_router
from app.assets.router import router as assets_router
from app.auth import sessions
from app.auth.router import router as auth_router
from app.config import get_settings
from app.content.router import router as content_router
from app.dashboard import router as dashboard_router
from app.hotels.router import router as hotels_router
from app.jobs.router import router as jobs_router
from app.observability import RequestContextMiddleware, configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warm up settings cache, validate critical env vars
    get_settings()
    yield
    # Shutdown: nothing to clean up for now


templates = Jinja2Templates(directory="app/templates")

READY_TIMEOUT_SECONDS = 2.0  # under the kubelet's readiness probe timeout


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    app = FastAPI(
        title="aicansolveit",
        description="AI-powered hotel content platform",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,  # hide docs in production
        redoc_url=None,
        lifespan=lifespan,
    )

    # Routers
    app.include_router(hotels_router, prefix="/api/v1/hotels", tags=["hotels"])
    app.include_router(assets_router, prefix="/api/v1/assets", tags=["assets"])
    app.include_router(content_router, prefix="/api/v1/content", tags=["content"])
    app.include_router(jobs_router, prefix="/internal/jobs", tags=["jobs"])
    app.include_router(public_upload_router, tags=["upload capabilities"])
    app.include_router(auth_router, tags=["authentication"])
    app.include_router(dashboard_router, tags=["dashboard"])

    @app.middleware("http")
    async def protect_dashboard_pages(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/dashboard"):
            response.headers["Cache-Control"] = "no-store"
            if response.status_code == 401:
                return RedirectResponse("/login", status_code=303)
        return response

    # Probes (platform plan 5.3), answered on the event loop (`async def`), so they never
    # queue behind request work in the thread pool: a slow liveness answer under load would
    # get every pod restarted at once.
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness: the process answers. No dependency checks: a restart can't fix them."""
        return {"status": "ok"}

    # Railway's health check (railway.toml) until the platform replaces Railway (5.9).
    app.add_api_route("/health", healthz, include_in_schema=False)

    probe_limiter = anyio.CapacityLimiter(1)  # its own thread, never the request pool's

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        """Readiness: Redis answers. Every operator request needs it (sessions), and it runs
        beside the app, so an unready pod is taken out of the Service until it's back.
        Supabase and the providers are not checked: they are outside the cluster, and an
        outage there would take every pod out at once without anything to fail over to."""
        try:
            with anyio.fail_after(READY_TIMEOUT_SECONDS):
                # abandon_on_cancel: the timeout answers now instead of waiting out a hung
                # ping. The thread keeps the limiter until the ping returns, so probes stay
                # unready (they time out) while Redis hangs, then recover by themselves.
                await anyio.to_thread.run_sync(
                    lambda: sessions.get_session_store().ping(),
                    limiter=probe_limiter,
                    abandon_on_cancel=True,
                )
        except (TimeoutError, sessions.RedisError) as exc:
            raise HTTPException(503, "not ready: Redis") from exc
        return {"status": "ready"}

    @app.get("/upload/{hotel_slug}")
    def upload_page(hotel_slug: str, request: Request):
        from app.database import get_supabase
        from app.hotels.service import get_hotel_by_slug

        db = get_supabase()
        hotel = get_hotel_by_slug(db, hotel_slug)
        response = templates.TemplateResponse(
            request, "upload/index.html", {"request": request, "hotel": hotel}
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    # Outermost, so every request gets an ID and an access log line, even one the app fails.
    app.add_middleware(RequestContextMiddleware)

    return app


app = create_app()
