"""
table_fees.py — Parser tabular de la seccion 'COMISIONES Y GASTOS'.

REGLA DE ORO: nunca regex sobre texto plano para comisiones.
La extraccion debe operar sobre la MATRIZ de la tabla, cruzando filas
(Gestion / Depositario / Suscripcion / Reembolso) con columnas
(Porcentaje / Base de calculo / Tramos).

Este modulo expone:
  parse_fees(table_rows, raw_text_class) -> dict con los 16 campos
                                            de comisiones del JSON

table_rows es la lista de listas que devuelve pdfplumber.extract_tables()
para la unica tabla de la seccion COMISIONES Y GASTOS dentro del slice
de la clase. Si por alguna razon no se proporcionan tablas (caso ZIP
preprocesado del proyecto), el modulo opera con un parser tabular
sintetico que reconstruye filas/columnas a partir del orden de tokens
de la version texto. Esto es un fallback documentado, NO la via de
produccion.

Este fichero se usa con dos motores intercambiables:
   1) pdfplumber.extract_tables()   -> motor real para PDF nativo
   2) tokenized text fallback       -> reconstruccion para folletos en
                                       formato preprocesado (ZIP)
"""

from __future__ import annotations
import re
from typing import Optional, List, Dict, Any

from .helpers import fmt_pct, parse_pct


# ---------------------------------------------------------------------------
# Spec declarativa de los 16 campos de comisiones
# ---------------------------------------------------------------------------
# Cada entrada describe DONDE buscar (fila > sub-base) y como tipar.
SPEC = {
    "COMIGEST": {"row": "gestion_directa",   "base": "patrimonio", "type": float},
    "COMIRDO":  {"row": "gestion_directa",   "base": "resultados", "type": float},
    "COMIDEPO": {"row": "depositario_directa", "base": "patrimonio", "type": float},
    "COMIAPEX": {"row": "suscripcion",       "base": "participe",  "type": float},
    "COMIREEX": {"row": "reembolso",         "base": "participe",  "type": float},
    "SDESCA":   {"row": "suscripcion",       "base": "descuento",  "type": str},
    "SDESCR":   {"row": "reembolso",         "base": "descuento",  "type": str},
    # Indirectas para SCOMIOTR
    "_indirecta_gestion":   {"row": "gestion_indirecta", "base": "patrimonio", "type": float},
    "_indirecta_deposito":  {"row": "depositario_indirecta", "base": "patrimonio", "type": float},
}


# ---------------------------------------------------------------------------
# Clasificador de filas (a partir del primer token de cada row)
# ---------------------------------------------------------------------------
_ROW_LABELS = [
    (re.compile(r'(?i)gesti[óo]n\s*\(anual\)'),                'gestion_header'),
    (re.compile(r'(?i)dep(?:o|ó)sit(?:ario|o)\s*\(anual\)'),  'depositario_header'),
    (re.compile(r'(?i)aplicada\s+directamente\s+al\s+fondo'),  'directa'),
    (re.compile(r'(?i)aplicada\s+indirectamente\s+al\s+fondo'),'indirecta'),
    (re.compile(r'(?i)^\s*suscripci[óo]n\s*$'),                'suscripcion'),
    (re.compile(r'(?i)^\s*reembolso\s*$'),                     'reembolso'),
]


def _classify_row(first_cell: str) -> Optional[str]:
    if not first_cell:
        return None
    for pat, label in _ROW_LABELS:
        if pat.search(first_cell):
            return label
    return None


def _is_pct_cell(cell: str) -> bool:
    return bool(re.search(r'\d+\s*(?:[.,]\d+)?\s*%', cell or ''))


def _is_base_resultados(cell: str) -> bool:
    return bool(re.search(r'(?i)resultado', cell or ''))


def _is_base_patrimonio(cell: str) -> bool:
    return bool(re.search(r'(?i)patrimonio', cell or ''))


def _is_base_descuento_fondo(cell: str) -> bool:
    """True si la celda 'Base de calculo' indica que el % es descuento a
    favor del fondo (penalizacion al participe que rompe la garantia)."""
    return bool(re.search(r'(?i)descuento\s+a\s+favor\s+del\s+fondo', cell or ''))


# ---------------------------------------------------------------------------
# Tramos temporales (garantizados)
# ---------------------------------------------------------------------------
RE_TRAMO_HASTA = re.compile(
    r'Hasta\s+el\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})',
    re.IGNORECASE,
)
RE_TRAMO_DESDE = re.compile(
    r'Desde\s+el\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})',
    re.IGNORECASE,
)


def normalize_date_ddmmyyyy(raw: str) -> Optional[str]:
    """'8.05.2025' -> '08/05/2025' | '05/05/26' -> '05/05/2026'.

    Acepta separador / o . y anio de 2 o 4 digitos. Anio 2-digit:
    50-99 -> 19xx, 00-49 -> 20xx (ventana 1950-2049)."""
    if not raw:
        return None
    m = re.match(r'\s*(\d{1,2})[./](\d{1,2})[./](\d{2,4})\s*$', raw)
    if not m:
        return None
    d, mo, y = m.group(1), m.group(2), m.group(3)
    if len(y) == 2:
        yi = int(y)
        y = f"20{y}" if yi < 50 else f"19{y}"
    return f"{int(d):02d}/{int(mo):02d}/{int(y):04d}"


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------
def _normalize_rows(table_rows: List[List[Optional[str]]]) -> List[List[str]]:
    """Limpia None y normaliza espacios en cada celda."""
    out: List[List[str]] = []
    for row in table_rows:
        clean = [(c or '').strip() for c in row]
        if any(clean):
            out.append(clean)
    return out


def _extract_fees_from_matrix(rows: List[List[str]]) -> Dict[str, Any]:
    """Cruce fila/columna sobre la matriz ya normalizada.

    Heuristica robusta: el 'header' Gestion/Depositario fija el contexto;
    las dos siguientes filas con 'Aplicada directamente/indirectamente'
    pertenecen a ese contexto. Dentro de una fila 'directa', si hay una
    sub-fila inmediatamente posterior con base 'Resultados' (sin etiqueta
    de fila, solo porcentaje + 'Resultados'), pertenece a la misma
    seccion (caso comision mixta de Cinvest).

    Soporta TRAMOS TEMPORALES (fondos garantizados): cuando tras una fila
    'Aplicada directamente al fondo' aparece una fila huerfana (primera
    celda vacia) cuya celda 'Tramos / plazos' contiene 'Hasta el' o
    'Desde el', se interpreta como un segundo tramo del mismo bloque.
    El valor vigente para COMIGEST/COMIDEPO es el del tramo 'Desde el'
    (periodo de garantia). Las fechas se exportan en _FCOMFIN_raw /
    _FINIGAR_raw para que guarantee_fields las consuma.
    """
    out: Dict[str, Any] = {
        "COMIGEST": 0.0, "COMIRDO": 0.0, "COMIDEPO": 0.0,
        "COMIAPEX": 0.0, "COMIREEX": 0.0,
        "SDESCA": "0,00%", "SDESCR": "0,00%",
        "_indirecta_gestion": 0.0, "_indirecta_deposito": 0.0,
        "_FCOMFIN_raw": None, "_FINIGAR_raw": None,
    }

    context: Optional[str] = None      # 'gestion' | 'depositario' | None
    last_was_directa = False

    i = 0
    while i < len(rows):
        row = rows[i]
        first = row[0] if row else ''
        label = _classify_row(first)

        if label == 'gestion_header':
            context = 'gestion'
            last_was_directa = False
            i += 1
            continue
        if label == 'depositario_header':
            context = 'depositario'
            last_was_directa = False
            i += 1
            continue

        # Fila tipo 'Aplicada directamente al fondo X% Patrimonio'
        if label == 'directa' and context:
            pct, base = _row_pct_and_base(row)
            tramo_text = _tramo_cell(row)
            # Mira si la siguiente fila es un segundo tramo del mismo bloque
            tramo_pct, tramo_dates = _maybe_consume_tramo(rows, i, tramo_text)
            if tramo_pct is not None:
                # Fondo con tramos: la comision vigente es la del tramo 'Desde el'
                pct = tramo_pct
                if tramo_dates.get("hasta") and not out["_FCOMFIN_raw"]:
                    out["_FCOMFIN_raw"] = tramo_dates["hasta"]
                if tramo_dates.get("desde") and not out["_FINIGAR_raw"]:
                    out["_FINIGAR_raw"] = tramo_dates["desde"]
                i += 2  # consume las dos filas del par de tramos
            else:
                i += 1
            if context == 'gestion':
                if base == 'patrimonio':
                    out["COMIGEST"] = pct
                elif base == 'resultados':
                    out["COMIRDO"] = pct
            else:  # depositario
                if base == 'patrimonio':
                    out["COMIDEPO"] = pct
            last_was_directa = True
            continue

        if label == 'indirecta' and context:
            pct, base = _row_pct_and_base(row)
            if context == 'gestion':
                out["_indirecta_gestion"] = pct
            else:
                out["_indirecta_deposito"] = pct
            last_was_directa = False
            i += 1
            continue

        # Sub-fila huerfana con porcentaje sobre 'Resultados' (caso Cinvest)
        if last_was_directa and context == 'gestion':
            joined = ' '.join(row)
            if _is_pct_cell(joined) and _is_base_resultados(joined):
                pct = parse_pct(joined)
                out["COMIRDO"] = pct
                i += 1
                continue

        # Filas Suscripcion / Reembolso (cuando existen como filas)
        if label in ('suscripcion', 'reembolso'):
            participe, descuento = _split_susc_reemb_pcts(row)
            pct_participe = parse_pct(participe) if participe else 0.0
            pct_descuento = parse_pct(descuento) if descuento else 0.0
            if label == 'suscripcion':
                out["COMIAPEX"] = pct_participe
                out["SDESCA"] = fmt_pct(pct_descuento) if descuento else "0,00%"
            else:
                out["COMIREEX"] = pct_participe
                out["SDESCR"] = fmt_pct(pct_descuento) if descuento else "0,00%"
            last_was_directa = False
            i += 1
            continue

        last_was_directa = False
        i += 1
    return out


def _tramo_cell(row: List[str]) -> str:
    """Devuelve la celda 'Tramos / plazos' (4a columna si existe), o ''."""
    if len(row) >= 4:
        return row[3] or ''
    return ''


def _maybe_consume_tramo(
    rows: List[List[str]], i: int, first_tramo: str
) -> tuple[Optional[float], Dict[str, Optional[str]]]:
    """Si la fila i+1 es un segundo tramo huerfano (primera celda vacia)
    con 'Desde el FECHA' en la 4a columna y la fila i tenia 'Hasta el FECHA',
    devuelve (pct_del_segundo_tramo, {hasta, desde}) ambos normalizados.
    En cualquier otro caso devuelve (None, {})."""
    if i + 1 >= len(rows):
        return None, {}
    nxt = rows[i + 1]
    if not nxt or (nxt[0] or '').strip():
        return None, {}
    second_tramo = _tramo_cell(nxt)
    m_hasta = RE_TRAMO_HASTA.search(first_tramo or '')
    m_desde = RE_TRAMO_DESDE.search(second_tramo or '')
    if not (m_hasta and m_desde):
        return None, {}
    # Localiza el % del segundo tramo
    pct = 0.0
    for cell in nxt[1:]:
        if _is_pct_cell(cell):
            pct = parse_pct(cell)
            break
    return pct, {
        "hasta": normalize_date_ddmmyyyy(m_hasta.group(1)),
        "desde": normalize_date_ddmmyyyy(m_desde.group(1)),
    }


def _split_susc_reemb_pcts(row: List[str]) -> tuple[str, str]:
    """Para filas Suscripcion / Reembolso devuelve (pct_participe, pct_descuento).

    Regla clave: si la celda 'Base de calculo' (3a) dice 'Descuento a
    favor del fondo', el porcentaje encontrado es DESCUENTO (SDESCA/SDESCR),
    no comision al participe. Si solo hay un % y la base es 'Importe
    suscrito' / 'Importe reembolsado' (default), el % es al participe.
    Si hay dos % en la fila, primero al participe, segundo descuento.
    """
    pct_cells = [c for c in row[1:] if _is_pct_cell(c)]
    base_cells = [c for c in row[1:] if (c and not _is_pct_cell(c))]
    base_text = ' '.join(base_cells)
    if len(pct_cells) >= 2:
        return pct_cells[0], pct_cells[1]
    if len(pct_cells) == 1:
        if _is_base_descuento_fondo(base_text):
            return '', pct_cells[0]
        return pct_cells[0], ''
    return '', ''


def _row_pct_and_base(row: List[str]) -> tuple[float, str]:
    """De una fila tipo 'Aplicada directamente al fondo | 0,55% | Patrimonio'
    extrae (pct, base in {'patrimonio','resultados',''})."""
    pct = 0.0
    base = ''
    for cell in row[1:]:
        if not pct and _is_pct_cell(cell):
            pct = parse_pct(cell)
        if not base:
            if _is_base_patrimonio(cell):
                base = 'patrimonio'
            elif _is_base_resultados(cell):
                base = 'resultados'
    # Si no encontro la base en celdas separadas, busca en el join
    if not base:
        joined = ' '.join(row)
        if _is_base_patrimonio(joined):
            base = 'patrimonio'
        elif _is_base_resultados(joined):
            base = 'resultados'
    return pct, base


# ---------------------------------------------------------------------------
# Fallback para folletos en formato preprocesado (ZIP)
# ---------------------------------------------------------------------------
def _build_synthetic_matrix(text_class: str) -> List[List[str]]:
    """Reconstruye una matriz aproximada a partir del texto plano del slice.
    Util cuando NO se dispone de PDF nativo. Documentado como fallback.

    Estrategia: localiza el bloque entre 'COMISIONES Y GASTOS' y la
    siguiente seccion ('INFORMACION SOBRE RENTABILIDAD' / 'OTROS DATOS' /
    fin). Cada linea no vacia se convierte en una fila; tokens separados
    por 2+ espacios o tabs se convierten en columnas.
    """
    m = re.search(
        r'COMISIONES\s+Y\s+GASTOS(.+?)'
        r'(?:INFORMACI[ÓO]N\s+SOBRE\s+RENTABILIDAD|'
        r'OTROS\s+DATOS\s+DE\s+INTER[ÉE]S|'
        r'INFORMACI[ÓO]N\s+DE\s+LA\s+CLASE\s+DE\s+PARTICIPACI[ÓO]N|'
        r'COMPARATIVA\s+DE\s+LAS\s+CLASES|'
        r'RESPONSABLES\s+DEL\s+CONTENIDO|$)',
        text_class,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return []
    block = m.group(1)
    rows: List[List[str]] = []
    for line in block.split('\n'):
        line = line.strip()
        if not line:
            continue
        # Salta las instrucciones legales largas y la nota '(*)' tras la tabla
        if line.startswith('(*)') or line.startswith('Comisiones aplicadas'):
            continue
        if 'Con independencia' in line or 'Los l' in line[:6]:
            break  # final de la tabla
        # Heuristica de columnas: divide por 2+ espacios o por separador de tabla
        cells = re.split(r'\s{2,}|\t+', line)
        # Si no se separo bien, intenta una segmentacion por etiquetas conocidas
        if len(cells) == 1:
            # Extrae el porcentaje y la base como columnas inferidas
            pct_m = re.search(r'(\d+(?:[.,]\d+)?\s*%)', line)
            base_m = re.search(r'(?i)(Patrimonio|Resultados)', line)
            label = line
            if pct_m:
                label = line[:pct_m.start()].strip()
            cells = [label]
            if pct_m:
                cells.append(pct_m.group(1).strip())
            if base_m:
                cells.append(base_m.group(1).strip())
        rows.append(cells)
    return rows


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
def parse_fees(table_rows: Optional[List[List]] = None,
               text_class: Optional[str] = None) -> Dict[str, Any]:
    """Devuelve los 16 campos de comisiones del JSON.

    Si recibe table_rows (preferido, motor pdfplumber), opera sobre
    la matriz real. Si no, reconstruye una matriz sintetica a partir
    del texto del slice de la clase.
    """
    rows: List[List[str]] = []
    if table_rows:
        rows = _normalize_rows(table_rows)
    if not rows and text_class:
        rows = _build_synthetic_matrix(text_class)

    raw = _extract_fees_from_matrix(rows) if rows else {
        "COMIGEST": 0.0, "COMIRDO": 0.0, "COMIDEPO": 0.0,
        "COMIAPEX": 0.0, "COMIREEX": 0.0,
        "SDESCA": "0,00%", "SDESCR": "0,00%",
        "_indirecta_gestion": 0.0, "_indirecta_deposito": 0.0,
        "_FCOMFIN_raw": None, "_FINIGAR_raw": None,
    }

    out: Dict[str, Any] = {
        # Numericas
        "COMIGEST":  raw["COMIGEST"],
        "COMIRDO":   raw["COMIRDO"],
        "COMIDEPO":  raw["COMIDEPO"],
        "COMIAPEX":  raw["COMIAPEX"],
        "COMIREEX":  raw["COMIREEX"],
        # Fijos
        "COMIAPEN":  "0",
        "COMIREEN":  "0",
        "COMIDIST":  "NO RELLENAR",
        # Derivadas S*
        "SCOMIG":    fmt_pct(raw["COMIGEST"]),
        "SCOMID":    fmt_pct(raw["COMIDEPO"]),
        "SCOMIA":    fmt_pct(raw["COMIAPEX"]),
        "SCOMIR":    fmt_pct(raw["COMIREEX"]),
        "SCOMIRDO":  f'{fmt_pct(raw["COMIRDO"])} (sobre resultados positivos anuales del fondo)',
        "SDESCA":    raw["SDESCA"],
        "SDESCR":    raw["SDESCR"],
        # SCOMIOTR: si hay indirectas, formatear; si no, NO RELLENAR
        "SCOMIOTR":  _format_scomiotr(
            raw["_indirecta_gestion"], raw["_indirecta_deposito"]
        ),
        # Privadas: fechas detectadas en tramos. Las consume guarantee_fields.
        # No estan en KEYS_ORDER, por lo que el assembler las ignora al volcar.
        "_FCOMFIN_raw": raw.get("_FCOMFIN_raw"),
        "_FINIGAR_raw": raw.get("_FINIGAR_raw"),
    }
    return out


def _format_scomiotr(g: float, d: float) -> str:
    if g <= 0 and d <= 0:
        return "NO RELLENAR"
    g_str = f"{g:.2f}".replace(".", ",")
    d_str = f"{d:.2f}".replace(".", ",")
    return f"Gestión: {g_str}% y Depósito: {d_str}%"
