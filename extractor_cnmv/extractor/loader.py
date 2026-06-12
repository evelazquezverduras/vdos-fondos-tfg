"""
loader.py — Extraccion de texto de un folleto.

Soporta dos modos:
  1) PDF nativo: usa pdfplumber.extract_text() pagina a pagina.
  2) Formato preprocesado del proyecto: archivo *.pdf que en realidad es un
     ZIP con N.txt y N.jpeg por pagina. Concatena los .txt en orden.

En ambos casos el output es una unica string con marcador [##PAGE##]
entre paginas, que segmenter.py usa para localizar saltos de pagina.
"""

from __future__ import annotations
import os
import re
import zipfile
import tempfile
from typing import Optional, List

PAGE_BREAK = "\n[##PAGE##]\n"


def _is_zip(path: str) -> bool:
    """Detecta si el archivo (aunque tenga extension .pdf) es realmente un ZIP."""
    try:
        with open(path, 'rb') as fh:
            sig = fh.read(4)
        return sig.startswith(b'PK\x03\x04')
    except Exception:
        return False


def _load_zipped_text(path: str) -> str:
    """Modo 2: ZIP con N.txt + N.jpeg por pagina."""
    pages: List[tuple[int, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp)
        for fname in os.listdir(tmp):
            if not fname.endswith('.txt'):
                continue
            stem = os.path.splitext(fname)[0]
            try:
                page_num = int(stem)
            except ValueError:
                continue
            with open(os.path.join(tmp, fname),
                      'r', encoding='utf-8', errors='ignore') as fh:
                pages.append((page_num, fh.read()))
    pages.sort(key=lambda x: x[0])
    return PAGE_BREAK.join(t for _, t in pages)


def _load_native_pdf(path: str) -> str:
    """Modo 1: PDF nativo via pdfplumber."""
    import pdfplumber  # import diferido (no romper si no esta instalado)
    chunks: List[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return PAGE_BREAK.join(chunks)


def load_text(path: str) -> str:
    """Devuelve el texto del folleto en formato unificado, con [##PAGE##]."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if _is_zip(path):
        return _load_zipped_text(path)
    return _load_native_pdf(path)


def load_native_tables(path: str) -> Optional[List]:
    """Devuelve la lista de tablas crudas (lista de listas) detectadas por
    pdfplumber. Solo aplicable a PDF nativo. Devuelve None para ZIP."""
    if _is_zip(path):
        return None
    import pdfplumber
    out: List = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables() or []
            for tbl in tables:
                out.append({"page": i + 1, "rows": tbl})
    return out


def normalize_whitespace(text: str) -> str:
    """Colapsa espacios multiples preservando saltos de linea."""
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
