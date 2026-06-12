"""
news.py — Modulo de noticias para complementar la recomendacion del Asesor IA.

Consulta Google Noticias (via feed RSS publico, sin API key) por un termino
de busqueda en espanol y clasifica los titulares con gpt-4o-mini en
{positivo, neutral, negativo} para devolver las N mas positivas.

API publica:
    fetch_google_news_rss(query, max_items=20) -> List[Dict]
    classify_sentiments(items, model="gpt-4o-mini") -> List[Dict]
    get_positive_news(query, max_results=5) -> List[Dict]
    topics_from_recommendation(rec, profile) -> List[str]

Cada item devuelto es un dict con:
    {
      "title": str, "link": str, "source": str,
      "published": str, "summary": str,
      "sentiment": "positivo"|"neutral"|"negativo"|None,
      "sentiment_score": float|None,  # 1.0 positivo, 0.0 neutral, -1.0 negativo
    }
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


_RSS_TEMPLATE = (
    "https://news.google.com/rss/search?q={q}&hl=es-419&gl=ES&ceid=ES:es"
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_HTTP_TIMEOUT = 10  # segundos

# Mapeo de etiquetas/sectores del catalogo VDOS -> termino de busqueda
# en lenguaje natural para Google Noticias.
_SECTOR_QUERIES: Dict[str, str] = {
    "tecnología": "sector tecnologia bolsa",
    "tecnologia": "sector tecnologia bolsa",
    "salud": "sector salud farmaceutico bolsa",
    "financiero": "sector bancario financiero bolsa",
    "energía": "sector energia petroleo gas",
    "energia": "sector energia petroleo gas",
    "materias primas": "materias primas commodities",
    "consumo": "sector consumo bolsa",
    "inmobiliario": "sector inmobiliario real estate bolsa",
    "renta fija pública": "deuda publica bonos soberanos",
    "renta fija publica": "deuda publica bonos soberanos",
    "renta fija privada": "bonos corporativos renta fija",
    "renta variable global": "bolsa mundial renta variable",
    "esg / sostenibilidad": "inversion sostenible ESG",
    "esg": "inversion sostenible ESG",
}

# Traduccion de BLOQUES de cartera (clase de activo) a busqueda real. Se hace
# por contencion de palabra clave porque los labels los redacta el LLM y son
# libres ("RF Euro Corto Plazo", "RV Internacional Diversificada", ...).
_BLOQUE_QUERIES: Dict[str, str] = {
    "rf ": "fondos de renta fija mercado",
    "renta fija": "fondos de renta fija mercado",
    "monetar": "fondos monetarios mercado",
    "rv ": "bolsa renta variable fondos",
    "renta variable": "bolsa renta variable fondos",
    "mixto": "fondos mixtos inversion bolsa",
    "mixta": "fondos mixtos inversion bolsa",
    "emergent": "mercados emergentes bolsa fondos",
    "tecnolog": "sector tecnologia bolsa",
    "salud": "sector salud farmaceutico bolsa",
    "energia": "sector energia bolsa",
    "energía": "sector energia bolsa",
    "inmobili": "sector inmobiliario bolsa",
}


def _bloque_a_query(block: str) -> Optional[str]:
    """Traduce un bloque de cartera a una query de noticias real, o None.

    Devuelve None si no reconocemos la clase de activo: en ese caso es mejor
    no generar tema que mandar el label literal a Google News."""
    nb = _normalize(block)
    if nb in _SECTOR_QUERIES:
        return _SECTOR_QUERIES[nb]
    for kw, q in _BLOQUE_QUERIES.items():
        if kw in nb:
            return q
    return None


# ---------------------------------------------------------------------------
# RSS fetcher
# ---------------------------------------------------------------------------
def _strip_html(s: str) -> str:
    """Limpia tags HTML basicos y entidades, para descripciones del feed."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_rss(xml_text: str) -> List[Dict[str, Any]]:
    """Parsea el XML de un feed RSS 2.0 y devuelve la lista de items."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    out: List[Dict[str, Any]] = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = _strip_html(item.findtext("description") or "")
        # Google News mete el medio en <source>
        src_el = item.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        out.append({
            "title": title,
            "link": link,
            "source": source,
            "published": pub,
            "summary": desc,
            "sentiment": None,
            "sentiment_score": None,
        })
    return out


@lru_cache(maxsize=64)
def _cached_fetch(url: str, ts_bucket: int) -> str:
    """Descarga con cache (TTL = 10 min via ts_bucket)."""
    req = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(req, timeout=_HTTP_TIMEOUT) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_google_news_rss(query: str,
                          max_items: int = 20) -> List[Dict[str, Any]]:
    """Devuelve hasta `max_items` noticias del feed de Google Noticias para
    la query indicada. No requiere API key.

    Tirar el feed cada vez es caro: cacheamos por bucket de 10 min."""
    if not query or not query.strip():
        return []
    url = _RSS_TEMPLATE.format(q=quote_plus(query.strip()))
    ts_bucket = int(time.time() // 600)  # nuevo bucket cada 10 min
    try:
        xml_text = _cached_fetch(url, ts_bucket)
    except Exception as e:
        # No tiramos la UI por un fallo de red.
        return [{
            "title": f"[Error consultando Google Noticias: {e}]",
            "link": "", "source": "", "published": "",
            "summary": "", "sentiment": None, "sentiment_score": None,
        }]
    items = _parse_rss(xml_text)
    return items[:max_items]


# ---------------------------------------------------------------------------
# Sentimiento
# ---------------------------------------------------------------------------
_SENTIMENT_SYSTEM = (
    "Eres un clasificador de noticias financieras. Para CADA noticia devuelve "
    "dos campos: "
    "1) 'relevante': true SOLO si la noticia trata del SECTOR/TEMA indicado en "
    "la consulta (mercados, fondos, empresas cotizadas o macroeconomia de ese "
    "sector). Noticias locales, sucesos, deportes, fichajes laborales, "
    "ayuntamientos o temas ajenos al sector => relevante:false. "
    "2) 'sentimiento': 'positivo' | 'neutral' | 'negativo' para un inversor de "
    "fondos. Positivo = sube precio / buenas perspectivas / beneficios / "
    "rebajas de tipos favorables. Negativo = caidas, perdidas, sanciones, "
    "recesion, quiebra. Neutral = informativa o mixta. "
    "Responde UNICAMENTE con JSON valido."
)


def classify_sentiments(items: List[Dict[str, Any]],
                        model: str = "gpt-4o-mini",
                        tema: str = "",
                        ) -> List[Dict[str, Any]]:
    """Pide al LLM clasificacion en lote: sentimiento + relevancia al tema.

    Modifica `items` in-place anadiendo `sentiment`, `sentiment_score`
    (1.0 / 0.0 / -1.0) y `relevante` (bool). Si no hay OPENAI_API_KEY
    devuelve los items sin clasificar (sentiment None, relevante None)."""
    if not items:
        return items
    if not os.environ.get("OPENAI_API_KEY"):
        return items

    # Construir payload compacto: solo titulares + summary corto
    payload = []
    for i, it in enumerate(items):
        snippet = (it.get("summary") or "")[:200]
        payload.append({"id": i, "title": it.get("title", ""),
                        "snippet": snippet})

    user_msg = (
        f"Sector/tema objetivo: {tema or 'fondos de inversion'}\n"
        "Clasifica cada noticia (relevancia al tema + sentimiento). "
        "Devuelve JSON con esta forma exacta:\n"
        '{"resultados": [{"id": 0, "relevante": true, "sentimiento": "positivo"}, ...]}\n'
        'Valores de sentimiento permitidos: "positivo", "neutral", "negativo".\n\n'
        f"Noticias:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    try:
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SENTIMENT_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
    except Exception:
        return items

    score_map = {"positivo": 1.0, "neutral": 0.0, "negativo": -1.0}
    for r in data.get("resultados", []) or []:
        idx = r.get("id")
        s = (r.get("sentimiento") or "").strip().lower()
        if idx is None or not isinstance(idx, int):
            continue
        if 0 <= idx < len(items):
            if s in score_map:
                items[idx]["sentiment"] = s
                items[idx]["sentiment_score"] = score_map[s]
            # relevancia: por defecto True si el modelo no la marca explicita
            items[idx]["relevante"] = bool(r.get("relevante", True))
    return items


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------
def get_positive_news(query: str,
                      max_results: int = 5,
                      pool_size: int = 20,
                      classify: bool = True,
                      ) -> List[Dict[str, Any]]:
    """Para una query, devuelve hasta `max_results` noticias positivas.

    1) descarga `pool_size` noticias del feed,
    2) si `classify` y hay OPENAI_API_KEY, las clasifica en lote,
    3) ordena por score (positivas primero) y recorta a `max_results`.

    Si no hay clasificacion disponible, devuelve simplemente las primeras
    `max_results` del feed (sin etiqueta de sentimiento)."""
    items = fetch_google_news_rss(query, max_items=pool_size)
    if not items:
        return []
    if classify:
        classify_sentiments(items, tema=query)
        # Si la clasificacion funciono, devolvemos SOLO titulares positivos y
        # relevantes al tema: son los que ayudan al gestor a apoyar su decision.
        # No rellenamos con neutros/negativos (eso seria mentir bajo el rotulo
        # "Solo positivas"). Es preferible mostrar menos titulares.
        clasifico = any(it.get("sentiment_score") is not None for it in items)
        if clasifico:
            positivos = [
                it for it in items
                if it.get("sentiment_score") == 1.0
                and it.get("relevante") is not False
            ]
            return positivos[:max_results]
        # La clasificacion no se pudo ejecutar (sin API key / error): para no
        # dejar la seccion vacia, devolvemos el feed crudo sin etiqueta.
        return items[:max_results]
    return items[:max_results]


# ---------------------------------------------------------------------------
# Extraccion de temas desde la recomendacion del asesor
# ---------------------------------------------------------------------------
def _normalize(s: str) -> str:
    return (s or "").strip().lower()


def topics_from_recommendation(rec: Dict[str, Any],
                               profile: Optional[Dict[str, Any]] = None,
                               max_topics: int = 4,
                               ) -> List[Dict[str, str]]:
    """Deriva temas de busqueda a partir de la recomendacion y del perfil.

    Devuelve lista de dicts {"label": str, "query": str} en orden de
    relevancia. Prioriza los sectores explicitos del perfil; luego usa
    los P06 (sectores) etiquetados de los fondos recomendados."""
    profile = profile or {}
    seen: set[str] = set()
    out: List[Dict[str, str]] = []

    def _push(label: str, query: Optional[str] = None) -> None:
        key = _normalize(label)
        if not key or key in seen:
            return
        seen.add(key)
        out.append({"label": label, "query": query or label})

    # 1) Sectores explicitos del formulario
    for s in profile.get("sectores") or []:
        if not s or _normalize(s) == "sin preferencia":
            continue
        q = _SECTOR_QUERIES.get(_normalize(s), s)
        _push(s, q)

    # 2) Regiones explicitas del formulario (queries mas vagas, pero utiles)
    for r in profile.get("regiones") or []:
        if not r or _normalize(r) == "sin preferencia":
            continue
        _push(f"Mercado: {r}", f"bolsa {r} fondos inversion")

    # 3) P06 (sector/activo) de los fondos recomendados — usa labels ya
    # traducidos si el LLM las devolvio en el nombre del bloque
    try:
        from rag.labels import code_to_label
    except Exception:
        code_to_label = lambda var, code: code  # noqa: E731

    for f in rec.get("fondos_recomendados") or []:
        r = f.get("_record") or {}
        p06 = r.get("P06")
        if p06:
            label = code_to_label("P06", p06)
            # Si la traduccion fallo y nos devuelve el propio codigo
            # (p.ej. "P06_G35"), no lo usamos como tema de noticias.
            if label and not re.match(r"^P\d{2}_", label):
                q = _SECTOR_QUERIES.get(_normalize(label), label)
                _push(label, q)

    # 4) Bloques de la cartera modelo (frases tipo "RV Internacional USA",
    # "Mixto Diversificado"). NO se usan como query literal: esos labels no
    # son terminos periodisticos y devuelven ruido (noticias municipales,
    # etc.). Solo generan tema si sabemos traducirlos a una busqueda real.
    for b in (rec.get("cartera_modelo") or {}).get("asignacion") or []:
        block = b.get("bloque")
        if not block:
            continue
        q = _bloque_a_query(block)
        if q:
            _push(block, q)

    return out[:max_topics]
