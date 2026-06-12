"""
helpers.py — Utilidades compartidas: formato, parseo y limpieza de strings.
"""

from __future__ import annotations
import re
import unicodedata


# ---------------------------------------------------------------------------
# Formato numerico
# ---------------------------------------------------------------------------
def fmt_pct(v: float) -> str:
    """0.55 -> '0,55%'   |   0.0 -> '0,00%'."""
    if v is None:
        return "0,00%"
    return f"{float(v):.2f}%".replace(".", ",")


def parse_pct(text: str) -> float:
    """'0,55%' o '0.55%' o '5%' -> 0.55  /  5.0.

    Devuelve 0.0 si no encuentra numero parseable.
    """
    if text is None:
        return 0.0
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*%', str(text))
    if not m:
        return 0.0
    return float(m.group(1).replace(",", "."))


def parse_eur(text: str) -> float:
    """'500.000 euros' o '1.000.000 euros' o '200 euros' -> float."""
    if text is None:
        return 0.0
    # Quita 'euros', 'eur', 'EUR', '€' y separador de miles
    raw = re.sub(r'(?i)\b(euros?|eur|€)\b', '', str(text)).strip()
    raw = raw.replace('.', '').replace(',', '.')  # 1.000,5 -> 1000.5
    m = re.search(r'-?\d+(?:\.\d+)?', raw)
    return float(m.group(0)) if m else 0.0


# ---------------------------------------------------------------------------
# Normalizacion de nombres (NFONDO, busqueda en catalogos)
# ---------------------------------------------------------------------------
def strip_accents(s: str) -> str:
    """Elimina tildes pero conserva la letra. 'Multigestión' -> 'Multigestion'."""
    if not s:
        return s
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def clean_name_token(s: str) -> str:
    """Limpieza estandar para concatenacion en NFONDO:
       - upper
       - sin acentos
       - sin comas
       - sin sufijos ', FI' / 'FI' al final
       - sin espacios redundantes
    """
    if not s:
        return ""
    out = strip_accents(s).upper()
    out = out.replace(",", " ")
    # Quita sufijos FI / F.I. / SICAV al final
    out = re.sub(r'\b(?:F\.?I\.?|FI|SICAV)\s*$', '', out).strip()
    out = re.sub(r'\s+', ' ', out).strip()
    return out


def build_nfondo(paraguas: str, compartimento: str | None,
                 clase: str | None) -> str:
    """Construye el NFONDO segun la regla:
       Paraguas / Compartimento Clase  (con espacios alrededor del slash).

    - Limpia acentos, comas, sufijos FI.
    - Dedupe: si el compartimento empieza por el nombre del paraguas
      (caso Cinvest Multigestion / Creand World Equities), no lo duplica.
    """
    par = clean_name_token(paraguas or "")
    cmp_ = clean_name_token(compartimento or "")
    cls = clean_name_token(clase or "")

    # Dedupe: si compartimento contiene paraguas, quitar paraguas del prefijo
    if par and cmp_ and cmp_.startswith(par):
        cmp_ = cmp_[len(par):].lstrip(' /').strip()

    # Si el compartimento ya incluia el paraguas con barra (caso Cinvest),
    # tambien hay que limpiar barras sueltas
    cmp_ = re.sub(r'^/\s*', '', cmp_).strip()

    # Construccion final
    parts = [par]
    if cmp_:
        parts.append(cmp_)
    if cls and (not cmp_ or cls not in cmp_):
        # Patron B (clase sin compartimento) -> "PARAGUAS / CLASE"
        # Patron D (compartimento + clase)    -> "PARAGUAS / COMPARTIMENTO / CLASE"
        parts.append(cls)
    nfondo = " / ".join(p for p in parts if p)
    return nfondo.strip()


# ---------------------------------------------------------------------------
# Truncado de COMENT
# ---------------------------------------------------------------------------
def truncate_coment(text: str, max_chars: int = 1000) -> str:
    """Trunca preservando palabras (la regla del manual):
       texto[:1000].rsplit(' ', 1)[0] + '...'
    """
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head = text[:max_chars].rsplit(' ', 1)[0]
    return head + '...'


# ---------------------------------------------------------------------------
# Lookup tolerante en catalogos
# ---------------------------------------------------------------------------
def normalize_for_lookup(s: str) -> str:
    """Clave de busqueda canonica: upper, sin acentos, sin puntuacion,
    sin espacios multiples. Para tolerar variaciones tipograficas."""
    if not s:
        return ""
    out = strip_accents(s).upper()
    out = re.sub(r'[^\w\s]', ' ', out)
    out = re.sub(r'\s+', ' ', out).strip()
    return out
