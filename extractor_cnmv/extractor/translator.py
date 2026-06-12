"""
translator.py — Fase 2 del pipeline.

Convierte un registro de la fase 1 (literales del folleto) a uno con
codigos canonicos VDOS, usando el catalogo listapxx.xls.

Campos traducidos:
  P02      literal gestora     -> codigo P02_GXXXX
  P11      literal depositario -> codigo P11_GXXXX
  AUDITOR  literal auditor     -> codigo AUDITOR_GXXXX (si existe el codigo)
  P00      etiqueta P20        -> codigo P00_GXX (mapeo determinista para
                                  garantizados; resto via lookup)

P05 y P06 quedan en pausa (requieren LLM y se rellenaran en la fase 3).
Si el match no se encuentra, el campo conserva el literal original (no
se pierde informacion). Esto ayuda a auditar luego que cadenas no estan
en el catalogo.

Estrategia de matching:
  1) Normalizacion canonica agresiva: upper, sin acentos, sin puntuacion,
     sin sufijos legales (SA, SL, SGIIC, ...) y sin tokens de 1 caracter
     (que provienen de "S. G. I. I. C." tras quitar puntos).
  2) Match exacto post-normalizacion contra el catalogo.
  3) Fallback fuzzy con difflib.SequenceMatcher.ratio() y umbral 0.85.
"""

from __future__ import annotations
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Optional, Dict, Any, List, Tuple

from .catalogs import _load_listapxx, p20_to_p00


_RE_PUNCT = re.compile(r"[^\w\s]")
_RE_WS = re.compile(r"\s+")

# Tokens que aparecen tras quitar puntuacion en denominaciones legales y
# que NO ayudan a discriminar el nombre real.
_LEGAL_SUFFIX_TOKENS = {
    "SA", "SAU", "SL", "SLU", "SLNE", "SGIIC", "SICAV", "SCV",
    "FI", "FII", "SOCIEDAD", "GESTORA", "ANONIMA",
    "INC", "LLC", "LTD", "CORP", "COMPANIA",
    "GRUPO", "AUDITORES", "ASESORES",
    "SUCURSAL", "ESPANA",
}


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _canonical(label: Optional[str]) -> str:
    """Normaliza agresivamente para matching robusto.

    'GESTORA EJEMPLO UNO S. G. I. I. C., S. A.' -> 'GESTORA EJEMPLO UNO'
    'Gestora Ejemplo Dos, S.A., SGIIC'             -> 'GESTORA EJEMPLO DOS'
    """
    if not label:
        return ""
    s = _strip_accents(label).upper()
    s = _RE_PUNCT.sub(" ", s)
    s = _RE_WS.sub(" ", s).strip()
    out: List[str] = []
    for t in s.split():
        if len(t) == 1:
            continue
        if t in _LEGAL_SUFFIX_TOKENS:
            continue
        out.append(t)
    return " ".join(out)


@lru_cache(maxsize=8)
def _build_index(var: str) -> Tuple[Tuple[str, str, str], ...]:
    """Devuelve tupla inmutable de (canonical, label_original, code) del
    catalogo para una variable. Cacheada por var."""
    df = _load_listapxx()
    sub = df[df["var"] == var]
    rows: List[Tuple[str, str, str]] = []
    for _, row in sub.iterrows():
        label = str(row["label"]).strip()
        code = str(row["value"]).strip()
        canon = _canonical(label)
        if canon:
            rows.append((canon, label, code))
    return tuple(rows)


def _match(label: Optional[str], var: str,
           threshold: float = 0.85) -> Optional[str]:
    """Devuelve el codigo VDOS o None si no hay match suficiente."""
    if not label:
        return None
    target = _canonical(label)
    if not target:
        return None
    idx = _build_index(var)
    # 1) match canonico exacto
    for canon, _lbl, code in idx:
        if canon == target:
            return code
    # 2) fuzzy fallback
    best_ratio = 0.0
    best_code: Optional[str] = None
    for canon, _lbl, code in idx:
        r = SequenceMatcher(None, target, canon).ratio()
        if r > best_ratio:
            best_ratio = r
            best_code = code
    if best_ratio >= threshold:
        return best_code
    return None


def translate_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Devuelve copia con P02/P11/AUDITOR/P00/P05/P06/P20 traducidos a codigos.

    Si el match no se encuentra, conserva el literal original.
    P05/P06 esperan etiquetas legibles devueltas por el LLM (fase 3).
    P00 se conserva si ya viene como codigo (fase 3 lo deja como 'P00_GX').
    """
    out = dict(rec)
    out["P02"] = _match(rec.get("P02"), "P02") or rec.get("P02")
    out["P11"] = _match(rec.get("P11"), "P11") or rec.get("P11")
    out["AUDITOR"] = _match(rec.get("AUDITOR"), "AUDITOR") or rec.get("AUDITOR")
    p20 = rec.get("P20")
    # P00: si ya viene como codigo (P00_GX) lo dejamos; sino derivamos.
    p00_in = rec.get("P00")
    if isinstance(p00_in, str) and p00_in.startswith("P00_"):
        out["P00"] = p00_in
    else:
        out["P00"] = (
            p20_to_p00(p20)
            or _match(p20, "P00")
            or p00_in
        )
    # P05/P06: traducir etiqueta legible -> codigo VDOS via catalogo.
    out["P05"] = _match(rec.get("P05"), "P05") or rec.get("P05")
    out["P06"] = _match(rec.get("P06"), "P06") or rec.get("P06")
    # P20: NO se traduce. La regla metodologica de VDOS establece que P20
    # va siempre como literal del folleto, igual que P01/AUDITOR. La fase
    # de traduccion a codigos no toca P20.
    out["P20"] = p20
    return out


def translate_all(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [translate_record(r) for r in records]


# ---------------------------------------------------------------------------
# Auditoria: util para reportar que literales NO se han podido traducir
# ---------------------------------------------------------------------------
def audit_unmatched(records: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Devuelve {var: [literales no traducidos]} agrupado y unico.

    P20 NO se audita porque va siempre literal por contrato VDOS.
    """
    out: Dict[str, set] = {
        "P02": set(), "P11": set(), "AUDITOR": set(),
        "P05": set(), "P06": set(),
    }
    for r in records:
        for var in ("P02", "P11", "AUDITOR", "P05", "P06"):
            lit = r.get(var)
            if not lit:
                continue
            if var == "P05" and isinstance(lit, str) and lit.startswith("P05_"):
                continue
            if var == "P06" and isinstance(lit, str) and lit.startswith("P06_"):
                continue
            code = _match(lit, var)
            if code is None:
                out[var].add(lit)
    return {k: sorted(v) for k, v in out.items()}
