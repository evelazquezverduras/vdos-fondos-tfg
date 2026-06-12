"""
chat.py — Orquestador RAG. Une recuperacion semantica + LLM (gpt-4o-mini)
para responder preguntas en lenguaje natural sobre los fondos.

Flujo:
  1) embebe la pregunta del usuario
  2) recupera top-K de ChromaDB (con filtros opcionales)
  3) construye un contexto compacto con los registros recuperados
  4) llama al LLM con un system prompt que incluye glosario VDOS
  5) devuelve la respuesta + lista de ISINs citados

El system prompt incluye un mini-glosario de los codigos VDOS por si el
LLM ve metadatos con codigos en lugar de etiquetas legibles.
"""

from __future__ import annotations
import os
import re
from typing import List, Dict, Any, Optional, Tuple

from .embed import EmbeddingClient
from . import simple_store


_DEFAULT_MODEL = "gpt-4o-mini"


# Glosario corto de las taxonomias VDOS, para el system prompt.
_GLOSARIO = """\
Catálogos VDOS (códigos internos, por si aparecen en los datos):
- P00 (Categoría VDOS, 22 valores): RV NACIONAL, RVI EE.UU., RVI EUROPEA,
  RVI EMERGENTES, RVI JAPÓN, RVI RESTO, RV EURO, RV MIXTA, RV MIXTA
  INTERNACIONAL, RF GARANTIZADO, RV GARANTIZADO, MONETARIO, MONETARIO
  INTERNACIONAL, RF CORTO, RF LARGO, RF INTERNACIONAL, RF MIXTA, RF MIXTA
  INTERNACIONAL, GLOBAL, INMOBILIARIO, FONDO DE INVERSIÓN LIBRE, SIN
  CLASIFICAR.
- P05 (Región/Divisa, 58 valores): ZONA EURO / EUR, USA / USD, JAPÓN / JPY,
  EMERGENTES / MULTIDIVISA, GLOBAL / MULTIDIVISA, ESPAÑA / EUR, etc.
- P06 (Sector/Tipo activo, 64 valores): RENTA VARIABLE, RENTA FIJA,
  TECNOLOGÍA, FINANCIERO, SALUD, ENERGÍA, CONSUMO, MIXTO FLEXIBLE,
  RETORNO ABSOLUTO, etc.
"""


SYSTEM_PROMPT = (
    "Eres un asistente analista de fondos de inversión españoles regulados "
    "por la CNMV. Tienes acceso a un catálogo estructurado de fondos con "
    "su política de inversión, categoría, gestora, depositario y comisiones.\n\n"
    f"{_GLOSARIO}\n"
    "REGLAS DE RESPUESTA:\n"
    "1) Responde SIEMPRE en español, conciso y útil para inversores.\n"
    "2) Basa tu respuesta SOLO en los fondos del contexto proporcionado.\n"
    "3) Cita los fondos por su ISIN entre paréntesis. Ejemplo:\n"
    "   'Fondo Ejemplo Bonos 2027 (ES0000000001) invierte en deuda pública...'.\n"
    "4) Si la pregunta pide una comparativa, usa tablas/listas concisas.\n"
    "5) Si los datos del contexto no son suficientes para responder, "
    "dilo explícitamente. NO inventes fondos ni datos.\n"
    "6) Cuando menciones comisiones, usa porcentaje con coma española.\n"
    "7) Si la pregunta no es sobre fondos, redirige amablemente."
)


def _build_context_block(records: List[Dict[str, Any]]) -> str:
    """Formato compacto y legible para inyectar en el prompt del LLM."""
    blocks: List[str] = []
    for i, r in enumerate(records, 1):
        b = [f"[{i}] ISIN: {r.get('ISIN','')}  |  {r.get('NFONDO','')}"]
        for label, key in (
            ("Gestora", "P02"), ("Depositario", "P11"),
            ("Tipo", "P01"),
            ("Categoría CNMV (P20)", "P20"),
            ("Categoría VDOS (P00)", "P00"),
            ("Región (P05)", "P05"),
            ("Sector (P06)", "P06"),
            ("Plazo", "DMINR"),
            ("Benchmark", "INFOREFB"),
            ("Garantizado", "GARANT"),
            ("Vencimiento garantía", "FVENGAR"),
            ("Comisión gestión", "SCOMIG"),
            ("Comisión depositario", "SCOMID"),
            ("Comisión suscripción", "SCOMIA"),
            ("Comisión reembolso", "SCOMIR"),
        ):
            v = r.get(key)
            if v in (None, "", "No existe."):
                continue
            b.append(f"  - {label}: {v}")
        coment = (r.get("COMENT") or "").strip()
        if coment:
            # truncado defensivo: 1200 chars por fondo para no saturar prompt
            b.append(f"  - Política: {coment[:1200]}{'...' if len(coment) > 1200 else ''}")
        blocks.append("\n".join(b))
    return "\n\n".join(blocks)


def retrieve(
    query: str,
    top_k: int = 5,
    filters: Optional[Dict[str, Any]] = None,
    embedder: Optional[EmbeddingClient] = None,
) -> List[Dict[str, Any]]:
    """Recupera top-K records desde simple_store (NumPy).
    Devuelve registros con metadata + _similarity."""
    if embedder is None:
        embedder = EmbeddingClient(provider="auto")
    qvec = embedder.embed_query(query)
    return simple_store.query(qvec, top_k=top_k, filters=filters)


def answer(
    query: str,
    top_k: int = 5,
    filters: Optional[Dict[str, Any]] = None,
    model: str = _DEFAULT_MODEL,
    extra_records: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Pipeline completo: recupera + llama al LLM.

    Devuelve (texto_respuesta, registros_usados_como_contexto).

    `extra_records` permite forzar el contexto con registros del JSON
    completo (con COMENT íntegro y todas las 55 claves) en lugar de los
    truncados que vienen del documento indexado. Si se pasa, se usa esos.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY no esta definida. Define la variable de entorno."
        )

    hits = retrieve(query, top_k=top_k, filters=filters)
    # Si nos pasaron registros completos, sustituimos por ellos (mismo orden).
    if extra_records:
        by_isin = {r["ISIN"]: r for r in extra_records}
        merged = []
        for h in hits:
            r = by_isin.get(h["ISIN"], {})
            merged.append({**r, "_similarity": h.get("_similarity")})
        hits_for_ctx = merged
    else:
        hits_for_ctx = hits

    context = _build_context_block(hits_for_ctx)

    from openai import OpenAI
    client = OpenAI()
    user_prompt = (
        f"PREGUNTA DEL USUARIO:\n{query}\n\n"
        f"CONTEXTO (top-{top_k} fondos más relevantes):\n{context}"
    )
    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    text = resp.choices[0].message.content or ""
    return text, hits


def extract_cited_isins(text: str) -> List[str]:
    """Devuelve los ISINs que aparecen citados en la respuesta del LLM."""
    return list(dict.fromkeys(re.findall(r"\bES[A-Z0-9]{10}\b", text)))
