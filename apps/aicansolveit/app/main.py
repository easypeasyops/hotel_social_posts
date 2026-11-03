from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.hotels.router import router as hotels_router
from app.assets.router import router as assets_router
from app.content.router import router as content_router
from app.jobs.router import router as jobs_router
from app.auth.router import router as auth_router
from app.assets.public_router import router as public_upload_router
from app.dashboard import router as dashboard_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warm up settings cache, validate critical env vars
    get_settings()
    yield
    # Shutdown: nothing to clean up for now


templates = Jinja2Templates(directory="app/templates")


def create_app() -> FastAPI:
    settings = get_settings()

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

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/upload/{hotel_slug}")
    async def upload_page(hotel_slug: str, request: Request):
        from app.database import get_supabase
        from app.hotels.service import get_hotel_by_slug
        db = get_supabase()
        hotel = get_hotel_by_slug(db, hotel_slug)
        response = templates.TemplateResponse(
            request,
            "upload/index.html", {"request": request, "hotel": hotel}
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return app


app = create_app()
