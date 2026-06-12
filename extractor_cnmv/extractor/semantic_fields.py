"""
semantic_fields.py — Clasificacion P05 / P06 con LLM.

REGLA: el LLM trabaja con ETIQUETAS LEGIBLES.
La traduccion etiqueta -> codigo P05_GXXXX / P06_GXXXX se hace en local
con catalogs.py (los codigos internos NUNCA viajan al LLM).

Optimizacion: cachear la respuesta por (num_cnmv, compartimento) — la
politica de inversion es comun a todas las clases del compartimento.
"""

from __future__ import annotations
import json
import os
from functools import lru_cache
from hashlib import md5
from typing import Optional, Tuple, Dict

from .catalogs import llm_options, catalog_lookup, P05_CONSOLIDATED, P06_CONSOLIDATED


SYSTEM_PROMPT = """\
Eres un analista de fondos de inversion senior. Tu UNICA tarea es leer
la 'Politica de Inversion' de un folleto CNMV y devolver dos
clasificaciones segun catalogos cerrados.

REGLAS ESTRICTAS:
1. Devuelves un objeto JSON valido EXACTAMENTE con dos claves: "P05" y "P06".
2. El valor de cada clave debe ser una de las etiquetas EXACTAS de la
   lista de opciones. NO inventes etiquetas. NO traduzcas. NO abrevies.
3. Si la politica no permite decidir con certeza, elige la opcion mas
   conservadora ('GLOBAL / MULTIDIVISA' para P05, 'GLOBAL' para P06).
4. NO respondas nada fuera del JSON.

OPCIONES VALIDAS para P05 (zona geografica):
{p05_options}

OPCIONES VALIDAS para P06 (sector de actividad):
{p06_options}
"""


USER_TEMPLATE = """\
Politica de Inversion del fondo:
\"\"\"
{politica}
\"\"\"

Devuelve SOLO el JSON con las dos claves P05 y P06.
"""


def _build_system_prompt() -> str:
    p05 = "\n".join(f"- {k}" for k in P05_CONSOLIDATED.keys())
    p06 = "\n".join(f"- {k}" for k in P06_CONSOLIDATED.keys())
    return SYSTEM_PROMPT.format(p05_options=p05, p06_options=p06)


# ---------------------------------------------------------------------------
# Cache en memoria por (num_cnmv, compartimento)
# ---------------------------------------------------------------------------
_classification_cache: Dict[str, Tuple[str, str]] = {}


def _cache_key(num_cnmv: str, compartimento: Optional[str]) -> str:
    base = f"{num_cnmv or ''}|{compartimento or ''}"
    return md5(base.encode()).hexdigest()


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
def classify(politica: str,
             num_cnmv: Optional[str] = None,
             compartimento: Optional[str] = None,
             *,
             dry_run: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Devuelve (P05_code, P06_code) para una politica de inversion.

    - Si num_cnmv y compartimento son provistos, cachea la respuesta:
      una unica llamada al LLM por compartimento.
    - dry_run=True NO llama al LLM, devuelve (None, None). Util para
      pruebas offline y para el test_runner.
    """
    if not politica:
        return None, None

    if num_cnmv and compartimento is not None:
        key = _cache_key(num_cnmv, compartimento)
        if key in _classification_cache:
            return _classification_cache[key]
    else:
        key = None

    if dry_run or not os.environ.get("OPENAI_API_KEY"):
        # Fallback heuristico simple: busca pistas obvias en la politica
        p05_code, p06_code = _heuristic_classify(politica)
        if key:
            _classification_cache[key] = (p05_code, p06_code)
        return p05_code, p06_code

    p05_label, p06_label = _call_openai(politica)
    p05_code = catalog_lookup("P05", p05_label) if p05_label else None
    p06_code = catalog_lookup("P06", p06_label) if p06_label else None
    result = (p05_code, p06_code)
    if key:
        _classification_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# Llamada real a OpenAI (placeholder; activarla solo con API key)
# ---------------------------------------------------------------------------
def _call_openai(politica: str) -> Tuple[Optional[str], Optional[str]]:
    """Llamada real a OpenAI corporativo.
    Activada solo si OPENAI_API_KEY esta disponible en el entorno.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "Falta la libreria 'openai'. Instalala con: pip install openai"
        )

    client = OpenAI()  # toma OPENAI_API_KEY del entorno
    messages = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user",
         "content": USER_TEMPLATE.format(politica=politica[:5000])},
    ]
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
        return data.get("P05"), data.get("P06")
    except json.JSONDecodeError:
        return None, None


# ---------------------------------------------------------------------------
# Fallback heuristico (sin LLM) — solo para tests
# ---------------------------------------------------------------------------
def _heuristic_classify(politica: str) -> Tuple[Optional[str], Optional[str]]:
    """Clasificador trivial por palabras clave. Solo se usa cuando NO hay
    OPENAI_API_KEY (modo offline / tests). En produccion se ignora."""
    p = politica.upper()
    # P05
    if 'ESPAÑA' in p and ('USA' not in p and 'EUROPA' not in p):
        p05 = catalog_lookup("P05", "ESPAÑA / EUR")
    elif 'EE.UU' in p or 'EEUU' in p or 'ESTADOS UNIDOS' in p:
        p05 = catalog_lookup("P05", "USA / USD")
    elif 'JAPON' in p or 'JAPÓN' in p:
        p05 = catalog_lookup("P05", "JAPON / JPY")
    elif 'EMERGENT' in p:
        p05 = catalog_lookup("P05", "EMERGENTES / MULTIDIVISA")
    elif 'EUROPA' in p:
        p05 = catalog_lookup("P05", "EUROPA / MULTIDIVISA")
    elif 'OCDE' in p or 'GLOBAL' in p:
        p05 = catalog_lookup("P05", "GLOBAL / MULTIDIVISA")
    elif 'EURO' in p:
        p05 = catalog_lookup("P05", "ZONA EURO / EUR")
    else:
        p05 = catalog_lookup("P05", "GLOBAL / MULTIDIVISA")

    # P06
    if 'TECNOLOG' in p or 'DIGITAL' in p:
        p06 = catalog_lookup("P06", "TECNOLOGIA")
    elif 'BIOTECNOL' in p:
        p06 = catalog_lookup("P06", "BIOTECNOLOGIA")
    elif 'INMOBIL' in p:
        p06 = catalog_lookup("P06", "INMOBILIARIOS")
    elif 'RENTA FIJA' in p and 'CORTO' in p:
        p06 = catalog_lookup("P06", "RENTA FIJA CORTO PLAZO")
    elif 'RENTA FIJA' in p:
        p06 = catalog_lookup("P06", "RENTA FIJA")
    elif 'RENTA VARIABLE' in p:
        p06 = catalog_lookup("P06", "RENTA VARIABLE")
    elif 'RETORNO ABSOLUTO' in p or 'GESTION ALTERNATIVA' in p:
        p06 = catalog_lookup("P06", "RETORNO ABSOLUTO")
    else:
        p06 = catalog_lookup("P06", "GLOBAL")
    return p05, p06
