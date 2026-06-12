"""
regex_fields.py — Extraccion regex de los campos deterministas del folleto
(no incluye comisiones —van por parser tabular— ni P05/P06 —van por LLM—).

Cada extractor recibe el slice apropiado (text_fund / text_compartment /
text_class) y devuelve un valor o None.
"""

from __future__ import annotations
import re
from typing import Optional, Tuple

from .helpers import parse_eur

# ---------------------------------------------------------------------------
# Anclas regex
# ---------------------------------------------------------------------------
RE_FCREC = re.compile(
    r'Fecha\s+de\s+constituci[óo]n\s+del\s+Fondo\s*:\s*(\d{2}/\d{2}/\d{4})',
    re.IGNORECASE,
)
RE_FREG_CNMV = re.compile(
    r'Fecha\s+de\s+registro\s+en\s+la\s+CNMV\s*:\s*(\d{2}/\d{2}/\d{4})',
    re.IGNORECASE,
)
RE_GESTORA = re.compile(
    r'Gestora\s*:\s*([A-ZÁÉÍÓÚÑ0-9 .,&\-/()\']+?)\s+Grupo\s+Gestora\s*:',
    re.IGNORECASE,
)
RE_DEPOSITARIO = re.compile(
    r'Depositario\s*:\s*([A-ZÁÉÍÓÚÑ0-9 .,&\-/()\']+?)\s+Grupo\s+Depositario\s*:',
    re.IGNORECASE,
)
RE_AUDITOR = re.compile(
    r'Auditor\s*:\s*([^\n]+)', re.IGNORECASE,
)
RE_CATEGORIA_FULL = re.compile(
    r'Categor[íi]a\s*:\s*Fondo\s+de\s+(Inversi[óo]n|Fondos)\.\s*([^\n.]+)',
    re.IGNORECASE,
)
RE_PLAZO_BLOCK = re.compile(
    r'Plazo\s+indicativo\s+de\s+la\s+inversi[óo]n\s*:\s*(.+?)(?=Objetivo\s+de\s+gesti[óo]n|Pol[ií]tica\s+de\s+inversi[óo]n)',
    re.IGNORECASE | re.DOTALL,
)
RE_PLAZO_ANIOS = re.compile(
    r'(?:menos\s+de\s+|inferior\s+a\s+)?(\d+(?:[.,]\d+)?)\s*(años?|meses)\.?',
    re.IGNORECASE,
)
RE_PLAZO_HORIZONTE = re.compile(
    r'horizonte\s+temporal\s+del\s+fondo\s*\(([^)]+)\)',
    re.IGNORECASE,
)
RE_OBJETIVO_BENCHMARK = re.compile(
    r'Objetivo\s+de\s+gesti[óo]n\s*:?\s*(.+?)Pol[ií]tica\s+de\s+inversi[óo]n',
    re.IGNORECASE | re.DOTALL,
)
RE_DIVISA = re.compile(
    r'Divisa\s+de\s+denominaci[óo]n\s+de\s+las\s+participaciones\s*:\s*([^.\n]+)',
    re.IGNORECASE,
)
RE_TIPOPART = re.compile(
    r'Colectivo\s+de\s+inversores\s+a\s+los\s+que\s+se\s+dirige\s*:\s*(.+?)(?=Divisa\s+de\s+denominaci[óo]n|Divisa)',
    re.IGNORECASE | re.DOTALL,
)
RE_INV_MIN_INI = re.compile(
    r'Inversi[óo]n\s+m[ií]nima\s+inicial\s*:\s*([0-9.,]+)\s*(\w+)',
    re.IGNORECASE,
)
RE_INV_MIN_MANT = re.compile(
    r'Inversi[óo]n\s+m[ií]nima\s+a\s+mantener\s*:\s*([0-9.,]+)\s*(\w+)',
    re.IGNORECASE,
)
RE_TIPO_PART = re.compile(
    r'Esta\s+participaci[óo]n\s+es\s+de\s+(acumulaci[óo]n|reparto|distribuci[óo]n)',
    re.IGNORECASE,
)
RE_PERIOD_VLP = re.compile(
    r'Frecuencia\s+de\s+c[áa]lculo\s+del\s+valor\s+liquidativo\s*:?\s*([^\n.]+)',
    re.IGNORECASE,
)
RE_VOLMAXP = re.compile(
    r'Volumen\s+m[áa]ximo\s+de\s+'
    r'(?:participaciones|participaci[óo]n|patrimonio)'
    r'(?:\s+por\s+part[íi]cipe)?\s*:\s*'
    r'(.+?)'
    r'(?='
    r'\n\s*COMISIONES\s+Y\s+GASTOS'
    r'|\n\s*Comisiones\s+aplicadas'
    r'|\n\s*Principales\s+comercializadores'
    r'|\n\s*Prestaciones\s+o\s+servicios\s+asociados'
    r'|\n\s*INFORMACI[ÓO]N\s+SOBRE\s+RENTABILIDAD'
    r'|\n\s*INFORMACI[ÓO]N\s+(?:DEL\s+)?COMPARTIMENTO'
    r'|\n\s*INFORMACI[ÓO]N\s+DE\s+LA\s+CLASE'
    r'|\n\s*OTROS\s+DATOS\s+DE\s+INTER[ÉE]S'
    r'|\d+\s+[ÚU]ltima\s+actualizaci[óo]n\s+del\s+folleto'
    r'|\[##PAGE##\]'
    r')',
    re.IGNORECASE | re.DOTALL,
)
RE_GARANTIZADO = re.compile(
    r'(?:Fondo\s+Garantizado|garant[ií]a\s+de\s+rentabilidad|se\s+garantiza\s+que)',
    re.IGNORECASE,
)
RE_HEDGED = re.compile(
    r'(?:cobertura\s+(?:de\s+)?divisa|exposici[óo]n\s+a\s+riesgo\s+divisa[^\n.]*0\s*%|sin\s+exposici[óo]n\s+a\s+riesgo\s+divisa)',
    re.IGNORECASE,
)
# El bloque de SAPMIN es la narrativa que sigue inmediatamente al valor de
# 'Inversion minima a mantener: X euros.', hasta la siguiente seccion del
# folleto. Captura desde el primer caracter no-espacio tras el valor
# numerico (asi no se pierde el inicio de la frase aunque el PDF haya
# cortado el salto de linea entre el valor y el texto).
RE_SAPMIN_BLOCK = re.compile(
    r'Inversi[óo]n\s+m[ií]nima\s+a\s+mantener\s*:?\s*'
    r'\d[\d.,]*\s*\w+\.?\s*'
    r'(.+?)'
    r'(?='
    r'Principales\s+comercializadores'
    r'|COMISIONES\s+Y\s+GASTOS'
    r'|Volumen\s+m[áa]ximo\s+de\s+(?:participaci[óo]n|patrimonio)'
    # Cabeceras de seccion: deben venir tras salto de linea (no las menciones
    # inline dentro del propio parrafo, p.ej. "se detalla en «otros datos
    # de interes»").
    r'|\n\s*INFORMACI[ÓO]N\s+SOBRE\s+RENTABILIDAD'
    r'|\n\s*OTROS\s+DATOS\s+DE\s+INTER[ÉE]S'
    r'|\n\s*INFORMACI[ÓO]N\s+(?:DEL\s+)?COMPARTIMENTO'
    r'|\n\s*INFORMACI[ÓO]N\s+DE\s+LA\s+CLASE'
    r'|\[##PAGE##\]'
    r'|\d+\s+[ÚU]ltima\s+actualizaci[óo]n\s+del\s+folleto'
    r')',
    re.IGNORECASE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Extractores publicos
# ---------------------------------------------------------------------------
def fcrec(text_fund: str) -> Optional[str]:
    m = RE_FCREC.search(text_fund)
    return m.group(1) if m else None


def freg_cnmv(text_fund: str) -> Optional[str]:
    """Fecha de registro en la CNMV: dd/mm/aaaa (paralelo a fcrec)."""
    m = RE_FREG_CNMV.search(text_fund)
    return m.group(1) if m else None


def gestora_label(text_fund: str) -> Optional[str]:
    m = RE_GESTORA.search(text_fund)
    return m.group(1).strip() if m else None


def depositario_label(text_fund: str) -> Optional[str]:
    m = RE_DEPOSITARIO.search(text_fund)
    return m.group(1).strip() if m else None


def auditor_label(text_fund: str) -> str:
    m = RE_AUDITOR.search(text_fund)
    if not m:
        return "FOLLETO NO CONTIENE AUDITOR"
    return m.group(1).strip()


def categoria(text_compartment: str) -> Tuple[str, str]:
    """Devuelve (P01, P20) parseados del epigrafe 'Categoria:'."""
    m = RE_CATEGORIA_FULL.search(text_compartment)
    if not m:
        return "", ""
    p01 = f"Fondo de {m.group(1).strip().capitalize()}"
    p20 = m.group(2).strip().rstrip('.').upper()
    return p01, p20


_MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


def _format_hasta_el_dia(fecha_raw: str) -> Optional[str]:
    """'30/11/2027' -> 'Hasta el dia 30 de Noviembre de 2027.'"""
    m = re.match(r'\s*(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})\s*$', fecha_raw)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y = 2000 + y if y < 50 else 1900 + y
    mes = _MESES_ES.get(mo)
    if not mes:
        return None
    return f"Hasta el día {d} de {mes} de {y}."


def dminr(text_compartment: str) -> Optional[str]:
    """Plazo indicativo de la inversion.

    Prioridad:
      1. Numero explicito en plazo: devuelve solo 'X años' o 'X meses'
         (sin 'inferior a', 'menos de' ni punto final).
      2. Fecha horizonte temporal -> 'Hasta el dia N de Mes de AAAA.'.
      3. None.
    """
    m = RE_PLAZO_BLOCK.search(text_compartment)
    if not m:
        return None
    block = m.group(1)
    m_a = RE_PLAZO_ANIOS.search(block)
    if m_a:
        num = m_a.group(1).replace(',', '.').strip()
        unit = m_a.group(2).lower().strip()
        return f"{num} {unit}."
    m_h = RE_PLAZO_HORIZONTE.search(block)
    if m_h:
        formatted = _format_hasta_el_dia(m_h.group(1).strip())
        if formatted:
            return formatted
    return None


def benchmark(text_compartment: str) -> str:
    """INFOREFB: nombre del benchmark si esta claramente referenciado.

    Solo devuelve no-default cuando el bloque 'Objetivo de gestión'
    menciona explicitamente un indice (MSCI, FTSE, S&P, Stoxx, etc.)
    o trae 'índice de referencia'/'benchmark' con un nombre seguido.
    """
    m = RE_OBJETIVO_BENCHMARK.search(text_compartment)
    if not m:
        return "Sin Benchmark de Referencia"
    obj = m.group(1).strip()

    # Frases que cierran el caso = "no hay benchmark"
    if any(p in obj.lower() for p in [
        'no tiene', 'no se gestiona', 'no se sigue', 'sin benchmark',
        'no esta gestionado', 'no está gestionado',
        'no toma como referencia', 'no utiliza ningún índice',
    ]):
        return "Sin Benchmark de Referencia"

    # Busca un nombre concreto de indice (MSCI/FTSE/STOXX/S&P/Bloomberg/...)
    INDEX_PATTERNS = [
        r'(MSCI[\w\s\-]+?(?:Index|Net Total Return|TR)\s*\w*)',
        r'(FTSE[\w\s\-]+?(?:Index|Total Return)?)',
        r'(STOXX[\w\s\-]+?\d*)',
        r'(S\s*&\s*P\s+\d+[\w\s\-]*)',
        r'(Bloomberg[\w\s\-]+?Index)',
        r'(Bloomberg Barclays[\w\s\-]+)',
        r'(EURO\s*STOXX\s*\d+\w*)',
        r'(Russell\s+\d+[\w\s\-]*)',
        r'(Nikkei\s*\d+\w*)',
        r'(IBEX\s*\d+\w*)',
    ]
    for pat in INDEX_PATTERNS:
        mi = re.search(pat, obj, re.IGNORECASE)
        if mi:
            return mi.group(1).strip()

    # Si no encontro indice por nombre pero hay frase 'índice de referencia X'
    mi = re.search(r'(?:índice|indice)\s+de\s+referencia\s*[:\s]+([^\n.]{4,80})',
                   obj, re.IGNORECASE)
    if mi:
        return mi.group(1).strip()

    return "Sin Benchmark de Referencia"


def divisa(text_class: str) -> Optional[str]:
    m = RE_DIVISA.search(text_class)
    return m.group(1).strip().rstrip('.') if m else None


def tipopart(text_class: str) -> str:
    m = RE_TIPOPART.search(text_class)
    if not m:
        return "No existe"
    return m.group(1).strip().rstrip('.')


def aportacion_minima(text_class: str) -> Tuple[float, str]:
    """Devuelve (APMIN: float, UAPMIN: str)."""
    m = RE_INV_MIN_INI.search(text_class)
    if not m:
        return 0.0, "euros"
    val = parse_eur(m.group(1))
    unit = m.group(2).lower().strip()
    return val, unit


def minimant(text_class: str) -> Tuple[float, str]:
    m = RE_INV_MIN_MANT.search(text_class)
    if not m:
        return 0.0, "euros"
    val = parse_eur(m.group(1))
    unit = m.group(2).lower().strip()
    return val, unit


def tipo_capdistr(text_class: str) -> Tuple[str, str]:
    """Devuelve (TIPO, PERIODIV)."""
    m = RE_TIPO_PART.search(text_class)
    if not m:
        return "Capitalización", "SIN PERIODICIDAD"
    word = m.group(1).lower()
    if word.startswith('acumul'):
        return "Capitalización", "SIN PERIODICIDAD"
    return "Distribución", ""  # PERIODIV se infiere por separado


def period_vlp(text_compartment: str) -> str:
    m = RE_PERIOD_VLP.search(text_compartment)
    return m.group(1).strip() if m else "Diaria"


def volmaxp(text_compartment: str) -> str:
    m = RE_VOLMAXP.search(text_compartment)
    if not m:
        return "No existe."
    val = m.group(1)
    val = re.sub(r'\[##PAGE##\]', ' ', val)
    val = re.sub(r'[ \t]+', ' ', val)
    val = re.sub(r'\s*\n\s*', ' ', val)
    val = re.sub(r'\s{2,}', ' ', val).strip().rstrip('.')
    return val if val else "No existe."


def garant_flag(text_compartment: str) -> int:
    """1 si garantizado, 0 si no."""
    return 1 if RE_GARANTIZADO.search(text_compartment) else 0


def hedged_flag(text_compartment: str) -> int:
    """1 si la divisa esta cubierta o exposicion 0%, 0 si no."""
    return 1 if RE_HEDGED.search(text_compartment) else 0


def sapmin(text_class: str) -> str:
    """Parrafo narrativo que sigue a la inversion minima a mantener.

    Captura desde el final del valor numerico ('10 euros.') hasta la
    siguiente seccion del folleto. Limpia marcadores [##PAGE##], pies de
    pagina ('N Ultima actualizacion del folleto: ...') y saltos de linea
    de justificacion del PDF para que la frase fluya como en el folleto."""
    m = RE_SAPMIN_BLOCK.search(text_class)
    if not m:
        return "No existe."
    block = m.group(1)
    # Limpia marcadores y pies de pagina que pudieran quedar dentro
    block = re.sub(r'\[##PAGE##\]', ' ', block)
    block = re.sub(
        r'(?im)^\s*\d+\s+[ÚU]ltima\s+actualizaci[óo]n\s+del\s+folleto[^\n]*$',
        '', block,
    )
    # Colapsa saltos de linea de justificacion (no de parrafo) y espacios
    block = re.sub(r'[ \t]+', ' ', block)
    block = re.sub(r'\s*\n\s*', ' ', block)
    block = re.sub(r'\s{2,}', ' ', block).strip()
    return block if block else "No existe."
