"""Traductor codigo VDOS -> etiqueta legible.

Envoltorio fino sobre extractor_cnmv/rag/labels.py. Aisla la web del
modulo original para que cualquier cambio futuro (cache, fallback) viva
aqui y no en el RAG.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Anadir extractor_cnmv al sys.path para poder importar rag.labels.
# tfg/web/backend/app/services/translate.py -> tfg/extractor_cnmv/
_EXTRACTOR_DIR = Path(__file__).resolve().parents[4] / "extractor_cnmv"
if str(_EXTRACTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTRACTOR_DIR))


def _import_labels():
    """Import lazy para que un error en listapxx no rompa import-time."""
    try:
        from rag import labels  # type: ignore

        return labels
    except Exception:
        return None


def code_to_label(var: Optional[str], code: Optional[str]) -> str:
    """Devuelve la etiqueta legible o el codigo si no se encuentra mapeo."""
    if not code:
        return ""
    if not var:
        return code
    mod = _import_labels()
    if mod is None:
        return code
    try:
        return mod.code_to_label(var, code) or code
    except Exception:
        return code


def display(rec: Dict[str, Any], key: str, expert: bool = False) -> str:
    """Mismo contrato que rag.labels.display, con fallback seguro."""
    v = rec.get(key)
    if v is None:
        return "-"
    mod = _import_labels()
    if mod is None:
        return str(v)
    try:
        return mod.display(rec, key, expert_mode=expert)
    except Exception:
        return str(v)
