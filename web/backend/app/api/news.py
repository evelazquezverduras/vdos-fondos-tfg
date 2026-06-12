"""Endpoints de noticias: topics derivados y feed clasificado."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Query

from ..schemas.news import NewsItem, NewsTopic
from ..services import adapters

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/topics", response_model=List[NewsTopic])
def topics(
    from_recommendation_id: str = Query(..., min_length=1),
    max_topics: int = Query(default=10, ge=1, le=20),
) -> List[NewsTopic]:
    """Deriva los temas relevantes de una recomendacion previa.

    Por defecto devuelve hasta 10 temas: sectores+regiones del perfil
    primero, luego P06 de los fondos recomendados y bloques de la cartera
    modelo. El frontend pinta un bloque de noticias por cada uno.
    """
    entry = adapters.get_recommendation(from_recommendation_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Recomendacion no encontrada o caducada de la cache.",
        )
    rec, profile = entry
    rows = adapters.call_news_topics(rec, profile, max_topics=max_topics)
    return [NewsTopic(label=r["label"], query=r["query"]) for r in rows]


@router.get("", response_model=List[NewsItem])
def news(
    topic: str = Query(..., min_length=1),
    classify: bool = Query(default=True),
    max_results: int = Query(default=5, ge=1, le=20),
) -> List[NewsItem]:
    """Descarga noticias para una query. Si classify=True usa el LLM."""
    try:
        items = adapters.call_news(topic, max_results=max_results, classify=classify)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google News: {e}")

    return [NewsItem(**_strip_keys(i)) for i in items]


def _strip_keys(d: dict) -> dict:
    """Conserva solo las claves del NewsItem."""
    allowed = {"title", "link", "source", "published", "summary",
               "sentiment", "sentiment_score"}
    return {k: v for k, v in d.items() if k in allowed}
