"""
segmenter.py — Detecta el patron estructural del folleto y emite, para
cada ISIN del documento, su scope completo (paraguas, compartimento,
clase) junto con el slice de texto correspondiente.

Patrones soportados:
  A. Fondo simple sin clases             -> 1 ISIN
  B. Fondo simple con N clases            -> N ISINs (mismo compartimento)
  C. Fondo por compartimentos sin clases  -> N ISINs (compartimentos = clases)
  D. Compartimentos + clases              -> M ISINs

Los slices se emiten en tres niveles:
  - text_fund        : cabecera del fondo paraguas (DATOS GENERALES)
  - text_compartment : bloque del compartimento (incluye Politica de inversion)
  - text_class       : bloque de la clase (incluye COMISIONES de la clase)

Para fondos simples (patron A), text_compartment == text_class == bloque
completo del documento despues de cabecera, y los identificadores de
compartimento/clase se dejan en None.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Anclas regex (literales del folleto CNMV)
# ---------------------------------------------------------------------------
RE_FOLLETO_NUM = re.compile(
    r'Folleto\s*N[º°]\s*Registro\s*Fondo\s*CNMV:\s*(\d+)', re.IGNORECASE
)
RE_FONDO_HEADER = re.compile(
    r'^([A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 .,&\'/\-]+,?\s*FI)\s*$', re.MULTILINE
)
RE_DATOS_GENERALES = re.compile(r'DATOS\s+GENERALES\s+DEL\s+FONDO', re.IGNORECASE)
RE_FONDO_POR_COMP = re.compile(r'Fondo\s+por\s+compartimentos', re.IGNORECASE)
RE_CLASES_DISPONIBLES = re.compile(
    r'CLASES\s+DE\s+PARTICIPACIONES\s+DISPONIBLES', re.IGNORECASE
)
RE_INFO_CLASE = re.compile(
    r'INFORMACI[ÓO]N\s+DE\s+LA\s+CLASE\s+DE\s+PARTICIPACI[ÓO]N', re.IGNORECASE
)
RE_INFO_COMPARTIMENTO = re.compile(
    r'INFORMACI[ÓO]N\s+(?:DEL|COMPARTIMENTO|DEL\s+COMPARTIMENTO)', re.IGNORECASE
)
RE_COMPARATIVA = re.compile(
    r'COMPARATIVA\s+DE\s+LAS\s+CLASES\s+DISPONIBLES', re.IGNORECASE
)
RE_RESPONSABLES = re.compile(
    r'RESPONSABLES\s+DEL\s+CONTENIDO\s+DEL\s+FOLLETO', re.IGNORECASE
)
RE_ISIN = re.compile(r'C[óo]digo\s*ISIN:\s*([A-Z]{2}[A-Z0-9]{10})')
RE_POLITICA_BLOCK = re.compile(
    # Colon OBLIGATORIO para no matchear menciones del disclaimer
    # ("...cualquiera que sea su política de inversión, está sujeto...").
    r'Pol[ií]tica\s+de\s+inversi[óo]n\s*:\s*(.*?)Informaci[óo]n\s+complementaria\s+sobre\s+las\s+inversiones',
    re.IGNORECASE | re.DOTALL
)
RE_CATEGORIA = re.compile(
    r'Categor[íi]a\s*:\s*([^\n]+?)\.?\s*$', re.IGNORECASE | re.MULTILINE
)


# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------
@dataclass
class Segment:
    """Un ISIN identificado en el folleto, con todo su scope."""
    isin: str
    pattern: str                     # 'A' | 'B' | 'C' | 'D'
    paraguas: str                    # nombre del fondo paraguas (raw)
    compartimento: Optional[str]     # nombre del compartimento (raw)
    clase: Optional[str]             # nombre de la clase (raw)
    text_fund: str = ""
    text_compartment: str = ""
    text_class: str = ""
    politica_inversion: str = ""
    categoria_raw: str = ""          # 'Fondo de Inversión. RENTA FIJA EURO.'


@dataclass
class FolletoSegmentation:
    pattern: str
    paraguas: str
    num_cnmv: Optional[str]
    text_fund: str
    segments: List[Segment] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _detect_pattern(text: str) -> str:
    has_compartimentos = bool(RE_FONDO_POR_COMP.search(text))
    has_clases = bool(RE_CLASES_DISPONIBLES.search(text)) or \
                 len(RE_INFO_CLASE.findall(text)) > 0
    if has_compartimentos and has_clases:
        return 'D'
    if has_compartimentos:
        return 'C'
    if has_clases:
        return 'B'
    return 'A'


def _extract_paraguas_name(text: str) -> str:
    """Extrae nombre del fondo paraguas. Busca primera linea tipo 'XXX, FI'
    despues del numero de registro CNMV."""
    m = RE_FOLLETO_NUM.search(text)
    start = m.end() if m else 0
    chunk = text[start:start + 600]
    for line in chunk.split('\n'):
        line = line.strip()
        if not line:
            continue
        if RE_FONDO_HEADER.match(line):
            return line
    # fallback: primera linea no vacia
    for line in chunk.split('\n'):
        line = line.strip()
        if line and 'CNMV' not in line.upper():
            return line
    return ""


def _extract_politica(slice_text: str) -> str:
    """Extrae la politica completa entre 'Politica de inversion:' e
    'Informacion complementaria sobre las inversiones:'. NO se trunca:
    el contenido va literal al campo COMENT del JSON. Se elimina el
    marcador interno [##PAGE##] que el loader insertaba entre paginas
    para que el texto fluya como en el folleto."""
    m = RE_POLITICA_BLOCK.search(slice_text)
    if not m:
        return ""
    block = m.group(1)
    # Limpia marcador de salto de pagina y normaliza saltos de linea sueltos
    block = re.sub(r'\s*\[##PAGE##\]\s*', ' ', block)
    block = re.sub(r'[ \t]+', ' ', block)
    block = re.sub(r'\n{2,}', '\n', block)
    return block.strip()


def _extract_categoria(slice_text: str) -> str:
    m = RE_CATEGORIA.search(slice_text)
    return m.group(1).strip() if m else ""


def _split_into_class_blocks(slice_text: str) -> List[tuple[str, str]]:
    """Para un slice que contiene N cabeceras INFORMACIÓN DE LA CLASE DE
    PARTICIPACION, devuelve [(nombre_clase, texto_bloque), ...].
    El nombre de la clase es la linea siguiente a la cabecera.
    """
    out: List[tuple[str, str]] = []
    matches = list(RE_INFO_CLASE.finditer(slice_text))
    if not matches:
        return out
    # Limites: cada bloque va desde su match hasta el siguiente o fin
    end_markers = matches + []  # copia
    boundaries: List[int] = []
    for m in matches:
        boundaries.append(m.start())
    # Anadir tope: COMPARATIVA o RESPONSABLES o fin de texto
    end_idx = len(slice_text)
    cmp_m = RE_COMPARATIVA.search(slice_text)
    resp_m = RE_RESPONSABLES.search(slice_text)
    candidates = [end_idx]
    if cmp_m:
        candidates.append(cmp_m.start())
    if resp_m:
        candidates.append(resp_m.start())
    end_idx = min(candidates)

    for i, m in enumerate(matches):
        start = m.start()
        next_start = matches[i + 1].start() if i + 1 < len(matches) else end_idx
        block = slice_text[start:next_start]
        # El nombre de la clase es la primera linea no vacia tras la cabecera
        after_header = slice_text[m.end():next_start].lstrip('\n').lstrip()
        first_line = after_header.split('\n', 1)[0].strip()
        # Filtra si la primera linea es 'Codigo ISIN' (caso degenerado)
        if first_line.upper().startswith('CÓDIGO') or \
           first_line.upper().startswith('CODIGO'):
            first_line = ""
        out.append((first_line, block))
    return out


RE_FOOTER_LINE = re.compile(
    r'^\s*\d+\s+[ÚU]ltima\s+actualizaci[óo]n\s+del\s+folleto\b',
    re.IGNORECASE,
)


def _first_meaningful_line(text: str, max_lines: int = 30) -> str:
    """Devuelve la primera linea util saltando vacias, marcadores [##PAGE##]
    y pies de pagina del folleto (numero + 'Ultima actualizacion del folleto')."""
    for line in text.split('\n')[:max_lines]:
        l = line.strip()
        if not l:
            continue
        if l.startswith('[##PAGE##]') or l == '[##PAGE##]':
            continue
        if RE_FOOTER_LINE.match(l):
            continue
        return l
    return ""


def _split_into_compartment_blocks(text: str, paraguas: str) -> List[tuple[str, str]]:
    """Para fondos por compartimentos, divide el texto en bloques por
    compartimento. Heuristica: cada compartimento empieza con su nombre
    (que suele ser 'PARAGUAS/COMPARTIMENTO') antes del 'Codigo ISIN'.

    Estrategia robusta:
      1. Localizar todos los 'Codigo ISIN'
      2. Para cada ISIN, retroceder hasta la cabecera de compartimento
         (linea que empiece por el paraguas o por 'INFORMACIÓN DEL
         COMPARTIMENTO').
    """
    blocks: List[tuple[str, str]] = []
    # Preferencia: usar el marcador explicito si existe
    explicit = list(RE_INFO_COMPARTIMENTO.finditer(text))
    if explicit:
        ends = [m.start() for m in explicit] + [len(text)]
        for i, m in enumerate(explicit):
            block = text[m.start():ends[i + 1]]
            # Nombre = primera linea util tras cabecera, ignorando pies de
            # pagina ('25 Ultima actualizacion del folleto: ...') y marcadores
            # [##PAGE##] que el loader inserta entre paginas.
            after = text[m.end():ends[i + 1]]
            name = _first_meaningful_line(after)
            blocks.append((name, block))
        return blocks

    # Si no hay cabecera explicita, usar ISIN como anchor y buscar el nombre
    # del compartimento como linea previa que contenga el paraguas o '/'
    isin_matches = list(RE_ISIN.finditer(text))
    if not isin_matches:
        return blocks
    par_clean = (paraguas or "").upper().replace(',', '').replace('FI', '').strip()
    boundaries = [0] + [m.start() for m in isin_matches[1:]] + [len(text)]
    for i, m in enumerate(isin_matches):
        start = boundaries[i]
        end = boundaries[i + 1]
        block = text[start:end]
        # Buscar nombre del compartimento: linea que contenga el paraguas con '/'
        # o la primera linea con '/' antes del ISIN
        name = ""
        # Mira las 30 lineas anteriores al ISIN dentro del bloque
        head = block[:m.start() - start]
        lines = [l.strip() for l in head.split('\n') if l.strip()]
        for line in reversed(lines[-30:]):
            if '/' in line and (par_clean[:6] in line.upper() or 'COMPARTIMENTO' in line.upper()):
                name = line
                break
        if not name and lines:
            name = lines[-1] if len(lines[-1]) < 120 else ""
        blocks.append((name, block))
    return blocks


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def segment(text: str) -> FolletoSegmentation:
    """Punto de entrada principal. Devuelve un objeto con la lista de
    Segments (uno por ISIN)."""
    text = text or ""
    pattern = _detect_pattern(text)
    paraguas = _extract_paraguas_name(text)
    num_cnmv_m = RE_FOLLETO_NUM.search(text)
    num_cnmv = num_cnmv_m.group(1) if num_cnmv_m else None

    # Cabecera comun del fondo: desde inicio hasta primera frontera
    end_fund_idx = len(text)
    for re_marker in (RE_INFO_CLASE, RE_INFO_COMPARTIMENTO):
        m = re_marker.search(text)
        if m and m.start() < end_fund_idx:
            end_fund_idx = m.start()
    # Si es patron A, el slice del 'fondo' es todo el documento
    text_fund = text[:end_fund_idx] if pattern in ('B', 'C', 'D') else text

    seg = FolletoSegmentation(
        pattern=pattern, paraguas=paraguas, num_cnmv=num_cnmv,
        text_fund=text_fund,
    )

    # ---- Patron A: 1 ISIN, sin clases ni compartimentos ----
    if pattern == 'A':
        m_isin = RE_ISIN.search(text)
        isin = m_isin.group(1) if m_isin else ""
        politica = _extract_politica(text)
        categoria = _extract_categoria(text)
        seg.segments.append(Segment(
            isin=isin, pattern='A', paraguas=paraguas,
            compartimento=None, clase=None,
            text_fund=text_fund, text_compartment=text, text_class=text,
            politica_inversion=politica, categoria_raw=categoria,
        ))
        return seg

    # ---- Patron B: 1 compartimento, N clases ----
    if pattern == 'B':
        # La politica esta en text_fund (es del fondo)
        politica = _extract_politica(text)
        categoria = _extract_categoria(text_fund)
        # Cada clase aporta su propio bloque
        # Slice "post-cabecera": desde el primer INFORMACIÓN DE LA CLASE
        first_clase = RE_INFO_CLASE.search(text)
        if not first_clase:
            return seg
        post_text = text[first_clase.start():]
        for clase_name, block in _split_into_class_blocks(post_text):
            m_isin = RE_ISIN.search(block)
            if not m_isin:
                continue
            seg.segments.append(Segment(
                isin=m_isin.group(1), pattern='B', paraguas=paraguas,
                compartimento=None, clase=clase_name,
                text_fund=text_fund,
                text_compartment=text_fund,   # politica del fondo
                text_class=block,
                politica_inversion=politica, categoria_raw=categoria,
            ))
        return seg

    # ---- Patrones C y D: compartimentos (con o sin clases internas) ----
    # Slice "post-cabecera": tras DATOS GENERALES termina la cabecera comun.
    # Buscamos el primer compartimento.
    first_comp_idx = end_fund_idx
    post_text = text[first_comp_idx:]

    comp_blocks = _split_into_compartment_blocks(post_text, paraguas)
    for comp_name, comp_block in comp_blocks:
        politica = _extract_politica(comp_block)
        categoria = _extract_categoria(comp_block)

        # En patron C el compartimento contiene 1 ISIN (es la "clase")
        # En patron D contiene N clases internas
        clase_blocks = _split_into_class_blocks(comp_block)
        if pattern == 'C' or not clase_blocks:
            m_isin = RE_ISIN.search(comp_block)
            if not m_isin:
                continue
            seg.segments.append(Segment(
                isin=m_isin.group(1), pattern='C', paraguas=paraguas,
                compartimento=comp_name, clase=None,
                text_fund=text_fund, text_compartment=comp_block,
                text_class=comp_block,
                politica_inversion=politica, categoria_raw=categoria,
            ))
        else:
            for clase_name, cls_block in clase_blocks:
                m_isin = RE_ISIN.search(cls_block)
                if not m_isin:
                    continue
                seg.segments.append(Segment(
                    isin=m_isin.group(1), pattern='D', paraguas=paraguas,
                    compartimento=comp_name, clase=clase_name,
                    text_fund=text_fund, text_compartment=comp_block,
                    text_class=cls_block,
                    politica_inversion=politica, categoria_raw=categoria,
                ))
    return seg
