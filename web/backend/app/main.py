"""Punto de entrada de la API FastAPI.

Construye la app, monta CORS, expone los routers y opcionalmente sirve el
frontend estatico desde la misma instancia (modo dev sin nginx).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .api import asesor, compare, estudio, inicio, news
from .config import get_settings
from .services.catalog import get_catalog

logger = logging.getLogger("vdos.web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Carga el catalogo en memoria y propaga OPENAI_API_KEY al entorno.

    El .env de tfg/web/ siempre tiene prioridad sobre la variable del
    sistema: en maquinas con una OPENAI_API_KEY antigua en el entorno de
    Windows, sin esta sobreescritura nunca se usaba la del .env.
    """
    settings = get_settings()
    if settings.openai_api_key:
        prev = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
        if prev and prev != settings.openai_api_key:
            logger.info("OPENAI_API_KEY del sistema sobreescrita con la del .env")
        else:
            logger.info("OPENAI_API_KEY propagada desde .env al entorno")
    logger.info("Arrancando con JSON: %s", settings.extracted_json_resolved)
    try:
        cat = get_catalog()
        logger.info("Catalogo cargado: %d ISINs", len(cat.records))
    except Exception as e:
        logger.exception("Fallo al cargar el catalogo: %s", e)
        raise
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="VDOS Funds Explorer · API",
        description="Capa REST sobre el extractor + RAG + Asesor existentes.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # En desarrollo servimos el frontend desde el mismo proceso; los
    # navegadores cachean ES modules agresivamente y quedaba codigo viejo
    # tras cada edicion. Forzamos no-cache en /scripts /styles /assets.
    class NoCacheStaticMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response: Response = await call_next(request)
            path = request.url.path
            if path.startswith(("/scripts/", "/styles/", "/assets/")) or path.endswith(".html"):
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response

    if settings.serve_frontend:
        app.add_middleware(NoCacheStaticMiddleware)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(inicio.router)
    app.include_router(asesor.router)
    app.include_router(news.router)
    app.include_router(compare.router)
    app.include_router(estudio.router)

    # Frontend estatico opcional (modo dev all-in-one).
    if settings.serve_frontend and settings.frontend_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=settings.frontend_dir, html=True),
            name="frontend",
        )

    return app


app = create_app()


@app.exception_handler(FileNotFoundError)
async def _file_not_found_handler(request, exc: FileNotFoundError):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )
