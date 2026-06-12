"""
catalog_labels.py — Listas LEGIBLES de etiquetas P05 (zona geografica) y
P06 (sector/tipo de activo) que se pasan al LLM para *constrained generation*.

El modelo solo puede elegir una etiqueta de estas listas; nunca inventa una
nueva ni ve los codigos internos. La traduccion etiqueta -> codigo ocurre en
local (translator.py).

----------------------------------------------------------------------------
NOTA DE VERSION SANEADA
Las listas reales del catalogo del proveedor se han recortado a un conjunto
REDUCIDO de etiquetas de EJEMPLO, suficiente para que el pipeline funcione y
se entienda, sin reproducir el catalogo completo (confidencial). En la version
interna estas listas se cargan desde una hoja de calculo del catalogo.
----------------------------------------------------------------------------
"""

from __future__ import annotations
from functools import lru_cache
from typing import List, Tuple

# Subconjunto de EJEMPLO de etiquetas P05 (zona / divisa).
_P05_FALLBACK: Tuple[str, ...] = (
    "ZONA EURO / EUR", "EUROPA / MULTIDIVISA", "ESPAÑA / EUR",
    "USA / USD", "JAPON / JPY", "EMERGENTES / MULTIDIVISA",
    "GLOBAL / EUR", "GLOBAL / USD", "SIN CLASIFICAR",
)

# Subconjunto de EJEMPLO de etiquetas P06 (sector / activo).
_P06_FALLBACK: Tuple[str, ...] = (
    "RENTA FIJA", "RENTA VARIABLE", "TECNOLOGIA", "FINANCIERO",
    "SALUD", "ENERGIA", "GLOBAL", "DEUDA PUBLICA", "DEUDA PRIVADA",
    "MIXTO. HASTA 35% EN RV", "MIXTO. HASTA 75% EN RV",
    "RETORNO ABSOLUTO", "SIN CLASIFICAR",
)


def _load_from_catalog(var: str) -> List[str]:
    """En la version interna esto carga las etiquetas desde el catalogo
    (hoja de calculo). Aqui no hay catalogo, por lo que se usan los
    snapshots de ejemplo de arriba."""
    from ..catalogs import _load_listapxx
    df = _load_listapxx()
    sub = df[df["var"] == var][["label"]].drop_duplicates()
    return [str(x).strip() for x in sub["label"].tolist() if str(x).strip()]


@lru_cache(maxsize=1)
def _p05() -> List[str]:
    try:
        out = _load_from_catalog("P05")
        return out if out else list(_P05_FALLBACK)
    except Exception:
        return list(_P05_FALLBACK)


@lru_cache(maxsize=1)
def _p06() -> List[str]:
    try:
        out = _load_from_catalog("P06")
        return out if out else list(_P06_FALLBACK)
    except Exception:
        return list(_P06_FALLBACK)


# Constantes publicas que consume el clasificador.
P05_LABELS: List[str] = _p05()
P06_LABELS: List[str] = _p06()
