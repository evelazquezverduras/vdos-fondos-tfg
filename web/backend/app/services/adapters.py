"""Wrappers finos sobre extractor_cnmv/rag (advisor, news).

Centraliza la importacion lazy de los modulos del RAG, la propagacion de
errores y la traduccion de las dataclasses crudas del RAG al formato
publico de la API (etiquetas legibles, ids estables, etc.).
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

# Asegura sys.path al extractor (translate.py ya lo hace, pero idempotente).
_EXTRACTOR_DIR = Path(__file__).resolve().parents[4] / "extractor_cnmv"
if str(_EXTRACTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTRACTOR_DIR))

from rag import risk_config  # type: ignore  # fuente unica de bandas de riesgo


# ---------------------------------------------------------------------------
# Cache LRU en memoria de recomendaciones
# ---------------------------------------------------------------------------
_REC_CACHE_MAX = 32
_rec_cache: "OrderedDict[str, Tuple[dict, dict]]" = OrderedDict()
_rec_lock = Lock()


def store_recommendation(rec: Dict[str, Any], profile: Dict[str, Any]) -> str:
    """Guarda la recomendacion + perfil en cache y devuelve un id."""
    rid = uuid.uuid4().hex[:12]
    with _rec_lock:
        _rec_cache[rid] = (rec, profile)
        if len(_rec_cache) > _REC_CACHE_MAX:
            _rec_cache.popitem(last=False)
    return rid


def get_recommendation(rid: str) -> Optional[Tuple[dict, dict]]:
    with _rec_lock:
        return _rec_cache.get(rid)


# ---------------------------------------------------------------------------
# Adaptadores
# ---------------------------------------------------------------------------
class OpenAIKeyMissing(RuntimeError):
    """Se levanta cuando un adaptador necesita OPENAI_API_KEY y no esta."""


def _require_openai() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise OpenAIKeyMissing(
            "OPENAI_API_KEY no esta definida en el entorno. "
            "Configurala en .env para habilitar este endpoint."
        )


def _enriquecer_con_metricas_vdos(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Anade a cada record las metricas cuantitativas del CSV VDOS:
    r1a, ra3, sharpe, com_total, volatilidad. Estas son las que el LLM
    necesita ver para elegir bien (rentabilidad alta, comision baja,
    sharpe positivo).

    Si el ISIN no esta en SQLite, las metricas quedan a None y el LLM
    sabe que ese fondo no tiene datos fiables.
    """
    from . import funds_data
    enriched = []
    for r in records:
        isin = r.get("ISIN", "")
        meta = funds_data.get_meta(isin) if isin else None
        if meta:
            # Anadimos con prefijo _vdos_ para no chocar con claves canonicas
            r = dict(r)
            r["_vdos_r1a"] = meta.get("r1a")
            r["_vdos_ra3"] = meta.get("ra3")
            r["_vdos_sharpe"] = meta.get("sharpe")
            r["_vdos_com_total"] = meta.get("com_total")
            r["_vdos_volatilidad"] = meta.get("volatilidad")
            r["_vdos_patrimonio"] = meta.get("patrimonio_miles")
        enriched.append(r)
    return enriched


# ---------------------------------------------------------------------------
# Filtro determinista de idoneidad por perfil de riesgo (MiFID)
# ---------------------------------------------------------------------------
# La idoneidad es una restriccion DURA, no una preferencia: se aplica en
# codigo (auditable) ANTES del LLM, de modo que el modelo solo ordena,
# pondera y justifica sobre fondos ya admisibles. La volatilidad anualizada
# (dato real VDOS) es el indicador de riesgo cuantitativo; el PRIESGOF del
# folleto viene vacio en el JSON canonico, por eso no se usa aqui.

# Maximos de volatilidad por perfil: importados de risk_config (fuente unica).
# NO redefinir umbrales aqui; cambialos en rag/risk_config.py.
_VOL_MAX_POR_PERFIL = {
    perfil: risk_config.vol_max(perfil)
    for perfil in ("Conservador", "Moderado", "Agresivo")
}
_POOL_MINIMO = 12  # si el filtro deja menos candidatos, se relaja


def _norm_perfil(profile: Dict[str, Any]) -> str:
    """Normaliza perfil_riesgo a 'Conservador' | 'Moderado' | 'Agresivo'."""
    return risk_config.normaliza_perfil(profile.get("perfil_riesgo"))


def _es_renta_variable_pura(rec: Dict[str, Any]) -> bool:
    return str(rec.get("P20") or "").upper().startswith("RENTA VARIABLE")


def _filtrar_admisibles_por_perfil(
        records: List[Dict[str, Any]],
        profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Devuelve solo los fondos admisibles para el perfil de riesgo.

    Regla principal: volatilidad anualizada <= maximo del perfil. Guarda
    extra para CONSERVADOR: si un fondo no tiene volatilidad conocida pero
    su categoria es Renta Variable pura, se excluye. Si el filtro deja un
    universo demasiado pequeno, se relaja para no dejar al LLM sin
    candidatos (el prompt sigue conteniendo las reglas como respaldo).
    """
    perfil = _norm_perfil(profile)
    if not perfil:
        return records
    vol_max = _VOL_MAX_POR_PERFIL[perfil]

    def _admisible(r: Dict[str, Any], estricto: bool) -> bool:
        vol = r.get("_vdos_volatilidad")
        if isinstance(vol, (int, float)):
            return vol <= vol_max
        # Sin dato de volatilidad: solo se excluye RV pura en conservador.
        if estricto and perfil == "Conservador" and _es_renta_variable_pura(r):
            return False
        return True

    filtrados = [r for r in records if _admisible(r, estricto=True)]
    if len(filtrados) < _POOL_MINIMO:
        filtrados = [r for r in records if _admisible(r, estricto=False)]
    if len(filtrados) < _POOL_MINIMO:
        return records
    return filtrados


def _reparar_cartera(raw: Dict[str, Any],
                     profile: Dict[str, Any]) -> Dict[str, Any]:
    """Red de seguridad determinista sobre la cartera devuelta por el LLM.

    Descarta fondos cuya volatilidad real excede el tope del perfil y
    renormaliza los pesos al 100%. Deja constancia en las advertencias.
    """
    perfil = _norm_perfil(profile)
    if not perfil:
        return raw
    vol_max = _VOL_MAX_POR_PERFIL[perfil]
    fondos = raw.get("fondos_recomendados") or []
    if not fondos:
        return raw

    from . import funds_data
    validos: List[Dict[str, Any]] = []
    descartados: List[str] = []
    for f in fondos:
        isin = (f.get("isin") or "").strip()
        meta = funds_data.get_meta(isin) if isin else None
        vol = meta.get("volatilidad") if meta else None
        if isinstance(vol, (int, float)) and vol > vol_max:
            descartados.append(f.get("nombre") or isin)
        else:
            validos.append(f)

    if descartados and validos:
        total = sum((f.get("peso_cartera_pct") or 0) for f in validos)
        if total > 0:
            for f in validos:
                f["peso_cartera_pct"] = round(
                    100.0 * (f.get("peso_cartera_pct") or 0) / total, 1)
        raw["fondos_recomendados"] = validos
        nota = ("Control de idoneidad: se descartaron por exceder la "
                f"volatilidad del perfil {perfil}: " + ", ".join(descartados)
                + ".")
        prev = (raw.get("riesgos_y_advertencias") or "").strip()
        raw["riesgos_y_advertencias"] = (prev + " " + nota).strip()
    return raw


# ---------------------------------------------------------------------------
# Validaciones deterministas POST-respuesta (no dependen del prompt)
# ---------------------------------------------------------------------------
_PERFIL_PALABRAS = {
    "conservador": "Conservador",
    "moderado": "Moderado",
    "moderada": "Moderado",
    "agresivo": "Agresivo",
    "agresiva": "Agresivo",
}


def _renormalizar_pesos(fondos: List[Dict[str, Any]]) -> bool:
    """Ajusta peso_cartera_pct para que sumen 100. Devuelve True si toco algo."""
    total = sum((f.get("peso_cartera_pct") or 0) for f in fondos)
    if not fondos or total <= 0:
        return False
    if abs(total - 100.0) <= 0.5:
        return False
    for f in fondos:
        f["peso_cartera_pct"] = round(
            100.0 * (f.get("peso_cartera_pct") or 0) / total, 1)
    return True


def _num_es(s: str) -> Optional[float]:
    """Convierte '2,50' o '2.50' a float."""
    try:
        return float(s.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _corregir_perfil_en_texto(texto: str, perfil_ok: str) -> Tuple[str, bool]:
    """Sustituye 'perfil <otro>' por 'perfil <perfil_ok>'. Devuelve (texto, cambiado).

    Solo toca la coletilla 'perfil X' (afirmacion de idoneidad), que es el
    bug observado ('ideal para el perfil conservador' con cliente Moderado).
    No toca comparativos libres.
    """
    if not texto or not perfil_ok:
        return texto, False
    cambiado = False

    def _repl(m: "re.Match") -> str:
        nonlocal cambiado
        palabra = m.group(2).lower()
        canon = _PERFIL_PALABRAS.get(palabra)
        if canon and canon != perfil_ok:
            cambiado = True
            return f"{m.group(1)}{perfil_ok.lower()}"
        return m.group(0)

    nuevo = re.sub(r"(perfil(?:\s+de\s+riesgo)?\s+)(\w+)", _repl, texto,
                   flags=re.IGNORECASE)
    return nuevo, cambiado


def _validar_respuesta(raw: Dict[str, Any],
                       profile: Dict[str, Any],
                       isins_validos: set) -> Dict[str, Any]:
    """Red de seguridad determinista y auditable sobre la salida del LLM.

    1) Descarta fondos cuyo ISIN no exista en el catalogo (anti-alucinacion).
    2) Renormaliza los pesos para que sumen 100.
    3) Corrige incoherencias perfil<->lenguaje (el cliente es X, no Y).
    4) Coteja las cifras citadas (volatilidad, Sharpe) en la justificacion
       contra los datos reales del fondo y, si difieren, las corrige y deja
       constancia.
    Todo lo que se modifica se anota en riesgos_y_advertencias.
    """
    from . import funds_data
    fondos = raw.get("fondos_recomendados") or []
    perfil_ok = _norm_perfil(profile)
    avisos: List[str] = []

    # 1) ISIN en catalogo
    validos = []
    alucinados = []
    for f in fondos:
        isin = (f.get("isin") or "").strip()
        if isin and isin in isins_validos:
            validos.append(f)
        else:
            alucinados.append(isin or f.get("nombre") or "?")
    if alucinados:
        avisos.append("Se descartaron ISIN no presentes en el catalogo CNMV: "
                      + ", ".join(alucinados) + ".")
        raw["fondos_recomendados"] = validos
        fondos = validos

    # 2) Pesos suman 100
    if _renormalizar_pesos(fondos):
        avisos.append("Se renormalizaron los pesos de la cartera al 100%.")

    # 3, 4 y 5) Coherencia perfil + cifras citadas + categoria vs volatilidad
    from .catalog import get_catalog
    cat = get_catalog()
    cifras_corregidas = []
    categoria_incoherente = []
    for f in fondos:
        just = f.get("justificacion") or ""
        # 3) perfil
        just, cambiado = _corregir_perfil_en_texto(just, perfil_ok)
        # 4) cifras vs reales
        isin = (f.get("isin") or "").strip()
        meta = funds_data.get_meta(isin) if isin else None
        if meta:
            just, mm = _cotejar_cifras(just, meta)
            cifras_corregidas.extend(f"{isin}: {x}" for x in mm)
        # 5) categoria declarada (P06) vs volatilidad real: un fondo etiquetado
        #    "renta fija"/"monetario" con volatilidad alta esta mal clasificado
        #    en el catalogo (p. ej. un fondo INDICE de bolsa). Lo avisamos.
        rec = cat.by_isin.get(isin) if isin else None
        vol = meta.get("volatilidad") if meta else None
        etiqueta = str((rec or {}).get("P06") or "").lower()
        if (etiqueta and ("renta fija" in etiqueta or "monetar" in etiqueta)
                and isinstance(vol, (int, float)) and vol > 0.06):
            categoria_incoherente.append(
                f"{isin} figura como '{(rec or {}).get('P06')}' pero su "
                f"volatilidad real es {vol * 100:.1f}% (propia de renta variable)")
        f["justificacion"] = just

    # 3) perfil tambien en resumen y advertencias
    for campo in ("resumen_ejecutivo", "riesgos_y_advertencias"):
        nuevo, camb = _corregir_perfil_en_texto(raw.get(campo) or "", perfil_ok)
        if camb:
            raw[campo] = nuevo
            if "coherencia de perfil" not in " ".join(avisos):
                avisos.append(f"Se corrigio el perfil citado para alinearlo "
                              f"con el cliente ({perfil_ok}).")

    if cifras_corregidas:
        avisos.append("Se ajustaron cifras citadas a los datos reales del fondo ("
                      + "; ".join(cifras_corregidas) + ").")

    if categoria_incoherente:
        avisos.append("Posible error de categoria en catalogo: "
                      + "; ".join(categoria_incoherente) + ".")

    if avisos:
        prev = (raw.get("riesgos_y_advertencias") or "").strip()
        nota = "Control automatico: " + " ".join(avisos)
        raw["riesgos_y_advertencias"] = (prev + " " + nota).strip()
    return raw


def _cotejar_cifras(texto: str, meta: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Compara volatilidad y Sharpe citados con los reales y los corrige.

    Tolerancia: volatilidad +-0.1 pp; Sharpe +-0.05. Devuelve (texto, lista
    de correcciones realizadas)."""
    correcciones: List[str] = []

    # Volatilidad: "volatilidad ... 10.60%" -> meta['volatilidad']*100
    vol_real = meta.get("volatilidad")
    if isinstance(vol_real, (int, float)):
        vol_real_pct = vol_real * 100.0
        m = re.search(r"(volatilidad[^0-9%]{0,20})(\d+[.,]\d+)\s*%", texto, re.IGNORECASE)
        if m:
            citado = _num_es(m.group(2))
            if citado is not None and abs(citado - vol_real_pct) > 0.1:
                nuevo = f"{m.group(1)}{vol_real_pct:.2f}%"
                texto = texto[:m.start()] + nuevo + texto[m.end():]
                correcciones.append(f"volatilidad {citado:.2f}%->{vol_real_pct:.2f}%")

    # Sharpe: "Sharpe ... 1.99"
    sh_real = meta.get("sharpe")
    if isinstance(sh_real, (int, float)):
        m = re.search(r"(sharpe[^0-9-]{0,15})(-?\d+[.,]\d+)", texto, re.IGNORECASE)
        if m:
            citado = _num_es(m.group(2))
            if citado is not None and abs(citado - float(sh_real)) > 0.05:
                nuevo = f"{m.group(1)}{float(sh_real):.2f}"
                texto = texto[:m.start()] + nuevo + texto[m.end():]
                correcciones.append(f"Sharpe {citado:.2f}->{float(sh_real):.2f}")

    return texto, correcciones


def call_advisor(profile: Dict[str, Any],
                 records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Llama a rag.advisor.recommend con records enriquecidos con metricas
    VDOS (rentabilidad, sharpe, comisiones reales, volatilidad).

    Antes del LLM se aplica un filtro determinista de idoneidad por perfil
    de riesgo (banda de volatilidad), de modo que el modelo solo ordena y
    justifica sobre fondos admisibles. Tras la respuesta se revalida y
    repara la cartera (volatilidad fuera de banda, ISIN inexistentes, pesos,
    coherencia perfil<->lenguaje y cifras citadas). Asi la idoneidad MiFID y
    la coherencia NO dependen de que el LLM respete el prompt.
    """
    _require_openai()
    from rag.advisor import recommend  # type: ignore

    records_enriched = _enriquecer_con_metricas_vdos(records)
    admisibles = _filtrar_admisibles_por_perfil(records_enriched, profile)
    raw = recommend(profile, admisibles)
    raw = _reparar_cartera(raw, profile)
    isins_validos = {str(r.get("ISIN")) for r in records if r.get("ISIN")}
    raw = _validar_respuesta(raw, profile, isins_validos)
    return raw


def call_news_topics(rec: Dict[str, Any],
                     profile: Optional[Dict[str, Any]] = None,
                     max_topics: int = 6) -> List[Dict[str, str]]:
    """Deriva temas de noticias a partir de la recomendacion."""
    from rag.news import topics_from_recommendation  # type: ignore

    return topics_from_recommendation(rec, profile or {}, max_topics=max_topics)


def call_news(query: str,
              max_results: int = 5,
              classify: bool = True) -> List[Dict[str, Any]]:
    """Descarga noticias positivas para una query."""
    if classify:
        # No bloqueamos si no hay key: news.py degrada a 'sin clasificar'.
        pass
    from rag.news import get_positive_news  # type: ignore

    return get_positive_news(query.strip(), max_results=max_results,
                             pool_size=20, classify=classify)
