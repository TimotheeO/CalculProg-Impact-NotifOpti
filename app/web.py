import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import ROOT, Settings
from app.database import Database
from app.models import Event, Workshop

logger = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(ROOT / "app" / "templates"))


def paris_date(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H h %M")


TEMPLATES.env.filters["paris_date"] = paris_date


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(application):
        try:
            database.check_schema()
        except SQLAlchemyError as error:
            database.close()
            raise RuntimeError(
                "Base inaccessible. Exécuter d’abord : python -m app.cli init-db"
            ) from error
        except Exception:
            database.close()
            raise
        try:
            yield
        finally:
            database.close()

    application = FastAPI(
        title="ImpactFlow",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.database = database
    application.state.settings = settings
    application.mount(
        "/static", StaticFiles(directory=ROOT / "app" / "static"), name="static"
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException):
        if request.url.path == "/health":
            return JSONResponse(
                {"status": "unavailable"}, status_code=error.status_code
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "status": error.status_code,
                "message": "Cette page est introuvable."
                if error.status_code == 404
                else "Cette action n’est pas disponible.",
            },
            status_code=error.status_code,
            headers=error.headers,
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        # Ne pas journaliser les paramètres SQL ou les données personnelles.
        logger.error("Database unavailable: %s", type(error).__name__)
        if request.url.path == "/health":
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="error.html",
            status_code=503,
            context={
                "status": 503,
                "message": "Le service est momentanément indisponible. Réessayez dans un instant.",
            },
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        logger.error("Unexpected application error: %s", type(error).__name__)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="error.html",
            status_code=500,
            context={
                "status": 500,
                "message": "Une erreur est survenue. Réessayez dans un instant.",
            },
            headers={"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"},
        )

    @application.get("/health")
    def health():
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    @application.get("/", name="catalog")
    def catalog(request: Request):
        with database.sessions() as session:
            events = list(
                session.scalars(
                    select(Event)
                    .where(
                        Event.status == "published",
                        Event.participation_mode == "open",
                    )
                    .order_by(Event.starts_at, Event.id)
                )
            )
        return TEMPLATES.TemplateResponse(
            request=request, name="catalog.html", context={"events": events}
        )

    @application.get("/events/{slug}", name="event_detail")
    def event_detail(request: Request, slug: str):
        with database.sessions() as session:
            event = session.scalar(
                select(Event).where(
                    Event.slug == slug,
                    Event.status == "published",
                    Event.participation_mode == "open",
                )
            )
            if event is None:
                raise HTTPException(status_code=404)
            workshops = list(
                session.scalars(
                    select(Workshop)
                    .where(
                        Workshop.event_id == event.id,
                        Workshop.status == "active",
                    )
                    .order_by(Workshop.starts_at, Workshop.id)
                )
            )
        return TEMPLATES.TemplateResponse(
            request=request,
            name="event.html",
            context={"event": event, "workshops": workshops},
        )

    return application
