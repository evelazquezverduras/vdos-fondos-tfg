"""Schemas de noticias."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class NewsTopic(BaseModel):
    label: str
    query: str


class NewsItem(BaseModel):
    title: str
    link: str = ""
    source: str = ""
    published: str = ""
    summary: str = ""
    sentiment: Optional[str] = Field(
        None, description="positivo | neutral | negativo | null"
    )
    sentiment_score: Optional[float] = Field(
        None, description="1.0 / 0.0 / -1.0 segun sentimiento, null si no clasificado"
    )
