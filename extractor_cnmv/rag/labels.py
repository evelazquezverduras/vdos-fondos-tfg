"""
labels.py — Traduccion codigo VDOS -> etiqueta legible, para el toggle
'Modo experto' de la UI.

Carga el mapeo desde listapxx.xls (catalogo maestro VDOS) y cachea en
memoria. Si el catalogo no esta disponible, devuelve el codigo tal cual.

API:
    code_to_label(var, code) -> str
        var es "P02", "P11", "P00", "P05", "P06", "AUDITOR", "P20", "P01"
    display(record, key, expert_mode=False) -> str
        helper que devuelve codigo o label segun el modo.
"""

from __future__ import annotations
from functools import lru_cache
from typing import Dict, Optional


@lru_cache(maxsize=8)
def _index_for(var: str) -> Dict[str, str]:
    """{codigo -> label} para una variable del catalogo."""
    try:
        from extractor.catalogs import _load_listapxx
        df = _load_listapxx()
        sub = df[df["var"] == var][["value", "label"]].drop_duplicates()
        return {str(row["value"]).strip(): str(row["label"]).strip()
                for _, row in sub.iterrows()}
    except Exception:
        return {}


def code_to_label(var: str, code: Optional[str]) -> str:
    """Si code es un codigo conocido, devuelve la etiqueta legible.
    Si no, devuelve el code original."""
    if not code:
        return ""
    idx = _index_for(var)
    return idx.get(code, code)


def display(rec: dict, key: str, expert_mode: bool = False) -> str:
    """Helper de UI: devuelve la string que se muestra para `key`.

    - Si el campo guarda un codigo (P02_GXXXX, P11_GXXXX, P00_GX, P05_G..,
      P06_G..) y expert_mode=False, traduce a etiqueta legible.
    - Si expert_mode=True, se muestra el codigo + etiqueta entre parentesis.
    - Si el campo ya es literal (NFONDO, AUDITOR\"...\"), se devuelve tal cual.
    """
    v = rec.get(key)
    if v is None:
        return "-"
    sv = str(v)
    # Detectar si parece codigo VDOS
    if isinstance(v, str) and any(v.startswith(p) for p in (
            "P02_", "P11_", "P00_", "P05_", "P06_", "P20_")):
        var = v.split("_", 1)[0]
        label = code_to_label(var, v)
        if expert_mode:
            return f"{v}  —  {label}"
        return label or v
    return sv
