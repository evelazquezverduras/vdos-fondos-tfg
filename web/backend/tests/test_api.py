"""Tests imperativos sobre la API. No usar pytest fixtures (convencion del repo)."""

from __future__ import annotations

import sys
from pathlib import Path

# tfg/web/backend/tests/test_api.py -> tfg/web/backend
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.catalog import reset_catalog  # noqa: E402


def _client() -> TestClient:
    reset_catalog()
    return TestClient(app)


def test_health():
    c = _client()
    r = c.get("/api/health")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok"}
    print("OK /api/health")


def test_stats():
    c = _client()
    r = c.get("/api/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("isins", "gestoras", "categorias", "garantizados"):
        assert k in body, f"falta {k}"
        assert isinstance(body[k], int)
    assert body["isins"] == 453, f"se esperaban 453 ISINs, llegaron {body['isins']}"
    print(f"OK /api/stats -> {body}")


def test_distribucion_categoria():
    c = _client()
    r = c.get("/api/distribucion/categoria")
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list) and items
    assert all("label" in i and "count" in i for i in items)
    # En modo cliente no debe asomar el codigo VDOS
    assert all(i.get("code") is None for i in items)
    print(f"OK /api/distribucion/categoria -> {len(items)} items")


def test_distribucion_gestora_topn():
    c = _client()
    r = c.get("/api/distribucion/gestora?limit=10")
    assert r.status_code == 200, r.text
    items = r.json()
    assert 1 <= len(items) <= 10
    # Orden descendente por count
    counts = [i["count"] for i in items]
    assert counts == sorted(counts, reverse=True)
    print(f"OK /api/distribucion/gestora top10 -> top: {items[0]['label']}({items[0]['count']})")


def test_modo_experto_devuelve_codigo():
    c = _client()
    r = c.get("/api/distribucion/categoria", headers={"X-Modo-Experto": "1"})
    assert r.status_code == 200, r.text
    items = r.json()
    assert any(i.get("code") for i in items), "modo experto deberia exponer codigo"
    print("OK X-Modo-Experto expone codigos")


def test_index_status_no_revienta():
    c = _client()
    r = c.get("/api/index/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ready" in body
    print(f"OK /api/index/status -> ready={body['ready']}")


def test_advisor_sin_openai_devuelve_503():
    """Si no hay OPENAI_API_KEY, /api/advisor/recommend debe responder 503."""
    import os

    prev = os.environ.pop("OPENAI_API_KEY", None)
    try:
        # Tambien hay que limpiar el modulo importado para que la rama de
        # _require_openai relea el entorno actual.
        c = _client()
        body = {"profile": {"edad": 45, "capital": 50000, "perfil_riesgo": "Moderado"}}
        r = c.post("/api/advisor/recommend", json=body)
        assert r.status_code == 503, f"esperado 503, llego {r.status_code}: {r.text}"
        print(f"OK /api/advisor/recommend sin key -> 503")
    finally:
        if prev:
            os.environ["OPENAI_API_KEY"] = prev


def test_news_topics_404_si_id_no_existe():
    c = _client()
    r = c.get("/api/news/topics?from_recommendation_id=NOEXISTE12")
    assert r.status_code == 404, r.text
    print("OK /api/news/topics 404 para id inexistente")


def test_news_estructura_basica():
    """La descarga de Google News no requiere OPENAI; con classify=false
    debe devolver una lista (puede ser vacia si no hay red)."""
    c = _client()
    r = c.get("/api/news?topic=bolsa&classify=false&max_results=3")
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    if items:
        first = items[0]
        for k in ("title", "link", "source", "published", "summary"):
            assert k in first, f"falta {k}"
        print(f"OK /api/news -> {len(items)} items, primer titular: {first['title'][:60]!r}")
    else:
        print("OK /api/news -> sin items (probablemente sin red)")


if __name__ == "__main__":
    test_health()
    test_stats()
    test_distribucion_categoria()
    test_distribucion_gestora_topn()
    test_modo_experto_devuelve_codigo()
    test_index_status_no_revienta()
    test_advisor_sin_openai_devuelve_503()
    test_news_topics_404_si_id_no_existe()
    test_news_estructura_basica()
    print("\nTODOS OK")
