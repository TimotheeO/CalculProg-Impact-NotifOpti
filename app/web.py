import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth.http import Identity, current_identity, home_for
from app.auth.routes import router as auth_router
from app.auth.security import AuthError
from app.config import ROOT, Settings
from app.database import Database
from app.events.routes import router as events_router
from app.events.services import EventError
from app.journal import router as journal_router
from app.mailer import make_mailer
from app.models import Event, Workshop, utc_now
from app.participation.routes import router as participation_router
from app.worker import Scheduler
from app.workshops.routes import router as workshops_router

logger = logging.getLogger(__name__)
TEMPLATES = Jinja2Templates(directory=str(ROOT / "app" / "templates"))


def paris_date(value: datetime) -> str:
    return value.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H h %M")


TEMPLATES.env.filters["paris_date"] = paris_date


def create_app(
    settings: Settings | None = None, *, clock=utc_now, mailer=None
) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_url)
    transport = mailer if mailer is not None else make_mailer(settings)
    scheduler = Scheduler(database, settings, transport, clock)

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
            scheduler.start()
            yield
        finally:
            try:
                scheduler.close()
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
    application.state.clock = clock
    application.state.mailer = transport
    application.state.scheduler = scheduler
    application.state.templates = TEMPLATES
    application.include_router(auth_router())
    application.include_router(events_router())
    application.include_router(workshops_router())
    application.include_router(participation_router())
    application.include_router(journal_router())
    application.mount(
        "/static", StaticFiles(directory=ROOT / "app" / "static"), name="static"
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        sensitive = request.url.path.startswith(
            (
                "/connexion",
                "/deconnexion",
                "/activation-organisateur",
                "/admin",
                "/organisateur",
                "/espace",
            )
        )
        response.headers["Referrer-Policy"] = "same-origin"
        if sensitive or settings.cookie_name in request.cookies:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @application.exception_handler(AuthError)
    async def auth_error(request: Request, error: AuthError):
        identity = current_identity(request)
        back = (
            "/admin"
            if request.url.path.startswith("/admin")
            else "/activation-organisateur"
            if request.url.path.startswith("/activation-organisateur")
            else "/connexion"
        )
        if (
            error.status == 403
            and identity.user
            and not request.url.path.startswith("/activation-organisateur")
        ):
            back = home_for(identity.user)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="error.html",
            status_code=error.status,
            context={
                "status": error.status,
                "message": str(error),
                "back_url": back,
                "back_label": "Revenir au formulaire",
                "viewer": identity.user,
                "csrf_token": identity.record.csrf_token if identity.record else "",
            },
            headers={"Retry-After": "900"} if error.status == 429 else None,
        )

    @application.exception_handler(EventError)
    async def event_error(request: Request, error: EventError):
        identity = current_identity(request)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="error.html",
            status_code=error.status,
            context={
                "status": error.status,
                "message": str(error),
                "back_url": home_for(identity.user) if identity.user else "/connexion",
                "back_label": "Revenir à mon espace",
                "viewer": identity.user,
                "csrf_token": identity.record.csrf_token if identity.record else "",
            },
        )

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
    def catalog(
        request: Request, identity: Annotated[Identity, Depends(current_identity)]
    ):
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
            request=request,
            name="catalog.html",
            context={
                "events": events,
                "viewer": identity.user,
                "csrf_token": identity.record.csrf_token if identity.record else "",
            },
        )

    @application.get("/events/{slug}", name="event_detail")
    def event_detail(
        request: Request,
        slug: str,
        identity: Annotated[Identity, Depends(current_identity)],
    ):
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
            context={
                "event": event,
                "workshops": workshops,
                "viewer": identity.user,
                "csrf_token": identity.record.csrf_token if identity.record else "",
            },
        )

    return application
