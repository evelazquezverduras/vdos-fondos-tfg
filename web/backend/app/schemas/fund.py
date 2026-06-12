"""Schemas Pydantic compartidos por varias vistas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Stats(BaseModel):
    """KPIs agregados del catalogo."""

    isins: int = Field(..., description="Numero total de ISINs en el catalogo")
    gestoras: int = Field(..., description="Numero de gestoras distintas (P02)")
    categorias: int = Field(..., description="Numero de categorias VDOS distintas (P00)")
    garantizados: int = Field(..., description="ISINs con GARANT==1")


class DistribucionItem(BaseModel):
    """Una fila de un bar chart de distribucion."""

    label: str = Field(..., description="Etiqueta legible (ya traducida)")
    count: int = Field(..., description="Numero de ISINs en esta categoria")
    code: str | None = Field(None, description="Codigo VDOS original (solo modo experto)")


class IndexStatus(BaseModel):
    """Estado del indice de embeddings del RAG."""

    ready: bool
    docs: int = 0
    size_kb: int = 0
    model: str | None = None
    provider: str | None = None
    error: str | None = None
