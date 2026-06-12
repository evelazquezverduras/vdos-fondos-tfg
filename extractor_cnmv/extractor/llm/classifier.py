"""
classifier.py — Orquestador de clasificacion LLM (P05/P06) + derivacion P00.

API publica:
    classify_fund(record, client=None, dry_run=False) -> dict
        record  : registro de la fase 1/2 (literales). Usa COMENT, P20, P01,
                  num_cnmv y compartimento si estan presentes.
        client  : instancia GeminiClassifier (opcional; si None se crea con
                  defaults y dry_run del entorno).
        return  : dict {"P05": label|None, "P06": label|None, "P00": codigo}

El P05 y P06 devueltos son ETIQUETAS legibles (no codigos VDOS). La
traduccion etiqueta -> codigo VDOS la hace translator.py en la fase 2.
"""

from __future__ import annotations
from typing import Optional, Dict, Any

from .catalog_labels import P05_LABELS, P06_LABELS
from .gemini_client import GeminiClassifier
from .p00_rules import derive_p00


SYSTEM_INSTRUCTION = (
    "Eres un analista experto en clasificacion de fondos de inversion "
    "espanoles segun la metodologia VDOS. Dada la POLITICA DE INVERSION "
    "del fondo, asignale dos etiquetas:\n"
    "  - P05: region/divisa principal de inversion.\n"
    "  - P06: sector/tipo de activo principal.\n"
    "Reglas estrictas:\n"
    "  1) Elige UNA SOLA etiqueta de cada lista permitida. No inventes "
    "etiquetas nuevas.\n"
    "  2) Si la politica es muy generica o no encaja, usa 'SIN CLASIFICAR'.\n"
    "  3) No anadas comentarios. Devuelve UNICAMENTE el JSON pedido."
)


def _build_prompt(record: Dict[str, Any]) -> str:
    coment = (record.get("COMENT") or "").strip()
    p20 = (record.get("P20") or "").strip()
    p01 = (record.get("P01") or "").strip()
    p05_list = "\n".join(f"  - {x}" for x in P05_LABELS)
    p06_list = "\n".join(f"  - {x}" for x in P06_LABELS)

    return (
        f"{SYSTEM_INSTRUCTION}\n\n"
        f"=== LISTA PERMITIDA P05 ===\n{p05_list}\n\n"
        f"=== LISTA PERMITIDA P06 ===\n{p06_list}\n\n"
        f"=== CONTEXTO DEL FONDO ===\n"
        f"Tipo (P01): {p01}\n"
        f"Categoria CNMV (P20): {p20}\n\n"
        f"=== POLITICA DE INVERSION (COMENT) ===\n{coment}\n\n"
        f"=== JSON DE RESPUESTA ===\n"
        f'Responde con un objeto JSON con dos claves: "P05" y "P06".\n'
    )


def classify_fund(
    record: Dict[str, Any],
    client: Optional[GeminiClassifier] = None,
    num_cnmv: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Devuelve {'P05': label|None, 'P06': label|None, 'P00': codigo|None}.

    Si el cliente esta en dry-run o no tiene API key, P05/P06 vienen a None
    pero P00 puede salir igualmente con la tabla determinista (caso garantizados
    y muchas categorias que solo dependen de P20).
    """
    if client is None:
        client = GeminiClassifier()

    prompt = _build_prompt(record)
    p05, p06 = client.classify(
        prompt=prompt,
        num_cnmv=num_cnmv,
        compartimento=record.get("NFONDO"),  # mejor identificador disponible
        p05_labels=P05_LABELS,
        p06_labels=P06_LABELS,
    )
    p00 = derive_p00(record.get("P20"), p05, p06)
    return {"P05": p05, "P06": p06, "P00": p00}
