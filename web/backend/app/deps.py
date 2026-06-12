"""Dependencias inyectables de FastAPI (catalogo, modo experto, etc.)."""

from __future__ import annotations

from fastapi import Header

from .services.catalog import Catalog, get_catalog


def catalog_dep() -> Catalog:
    """Catalogo en memoria con los 453 registros y sus indices."""
    return get_catalog()


def expert_mode(x_modo_experto: str | None = Header(default=None)) -> bool:
    """Activa devolver codigos VDOS ademas de etiquetas legibles.

    En produccion ira gateado por auth real. Por ahora se confia en el header.
    """
    return x_modo_experto in ("1", "true", "yes")
