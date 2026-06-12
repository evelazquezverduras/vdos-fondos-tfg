"""Endpoints de la vista Inicio: stats, distribuciones y estado del indice."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Query

from ..deps import catalog_dep, expert_mode
from ..schemas.fund import DistribucionItem, IndexStatus, Stats
from ..services.catalog import Catalog

# Permitir import del modulo simple_store del extractor (esta en sys.path
# tras importar translate, pero lo aseguramos aqui por idempotencia).
_EXTRACTOR_DIR = Path(__file__).resolve().parents[4] / "extractor_cnmv"
if str(_EXTRACTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTRACTOR_DIR))


router = APIRouter(prefix="/api", tags=["inicio"])


@router.get("/stats", response_model=Stats)
def get_stats(cat: Catalog = Depends(catalog_dep)) -> Stats:
    """Devuelve los KPIs del catalogo para la vista Inicio."""
    return Stats(**cat.stats())


@router.get("/distribucion/categoria", response_model=List[DistribucionItem])
def distribucion_categoria(
    cat: Catalog = Depends(catalog_dep),
    expert: bool = Depends(expert_mode),
) -> List[DistribucionItem]:
    """Distribucion de fondos por categoria VDOS (P00). Etiquetas legibles."""
    rows = cat.distribution("P00", translate_var="P00")
    return [_to_item(r, expert) for r in rows]


@router.get("/distribucion/gestora", response_model=List[DistribucionItem])
def distribucion_gestora(
    cat: Catalog = Depends(catalog_dep),
    expert: bool = Depends(expert_mode),
    limit: int = Query(default=20, ge=1, le=200),
) -> List[DistribucionItem]:
    """Top-N gestoras por numero de fondos. P02 ya viene como etiqueta legible
    en el JSON canonico, asi que no se traduce."""
    rows = cat.distribution("P02", translate_var=None, limit=limit)
    return [_to_item(r, expert) for r in rows]


@router.get("/index/status", response_model=IndexStatus)
def index_status() -> IndexStatus:
    """Estado del indice de embeddings del RAG (rag.simple_store)."""
    try:
        from rag import simple_store  # type: ignore

        s = simple_store.status()
    except Exception as e:
        return IndexStatus(ready=False, error=f"No se pudo consultar el indice: {e}")

    if "error" in s:
        return IndexStatus(ready=False, error=s["error"])
    return IndexStatus(
        ready=True,
        docs=int(s.get("count", 0)),
        size_kb=int(s.get("size_kb", 0)),
        model=s.get("model"),
        provider=s.get("provider"),
    )


def _to_item(row: dict, expert: bool) -> DistribucionItem:
    """Oculta el codigo VDOS si no estamos en modo experto."""
    return DistribucionItem(
        label=row["label"],
        count=row["count"],
        code=row["code"] if expert else None,
    )
