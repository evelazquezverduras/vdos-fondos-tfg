"""Catalogo en memoria de los 453 registros + indices auxiliares.

Carga pdfs_extracted.json (etiquetas legibles) una sola vez al arrancar la API
y construye indices por gestora / categoria / ISIN. Los JSON son SOLO LECTURA.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..config import get_settings
from . import translate


class Catalog:
    """Catalogo de fondos en memoria.

    Atributos:
        records: lista de 453 dicts.
        by_isin: indice {ISIN -> record}.
        by_gestora: indice {label_gestora -> [records]}.
        by_p00: indice {codigo_P00 -> [records]}.
    """

    def __init__(self, records: List[Dict[str, Any]]) -> None:
        self.records: List[Dict[str, Any]] = records
        self.by_isin: Dict[str, Dict[str, Any]] = {
            r["ISIN"]: r for r in records if r.get("ISIN")
        }
        self.by_gestora: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.by_p00: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in records:
            if r.get("P02"):
                self.by_gestora[r["P02"]].append(r)
            if r.get("P00"):
                self.by_p00[r["P00"]].append(r)

    # ---- stats agregadas (Fase 1) -------------------------------------

    def stats(self) -> Dict[str, int]:
        """KPIs para la vista Inicio."""
        gestoras = {r.get("P02") for r in self.records if r.get("P02")}
        categorias = {r.get("P00") for r in self.records if r.get("P00")}
        garant = sum(1 for r in self.records if _is_garant(r))
        return {
            "isins": len(self.records),
            "gestoras": len(gestoras),
            "categorias": len(categorias),
            "garantizados": garant,
        }

    def distribution(
        self,
        key: str,
        translate_var: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Distribucion de registros por una clave canonica.

        - key: nombre de campo (P00, P02, ...)
        - translate_var: si se pasa, se traduce code -> label con labels.py.
        - limit: top-N (None = todas).
        """
        counts: Counter[str] = Counter(
            r.get(key) for r in self.records if r.get(key)
        )
        ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        if limit is not None:
            ordered = ordered[:limit]
        out: List[Dict[str, Any]] = []
        for code, n in ordered:
            label = translate.code_to_label(translate_var, code) if translate_var else code
            out.append({"label": label or code, "count": int(n), "code": code})
        return out


def _is_garant(rec: Dict[str, Any]) -> bool:
    """GARANT en el JSON puede venir como 0/1, True/False o string."""
    g = rec.get("GARANT")
    if g is None:
        return False
    if isinstance(g, bool):
        return g
    if isinstance(g, (int, float)):
        return int(g) == 1
    if isinstance(g, str):
        return g.strip().lower() in ("1", "si", "sí", "true", "yes")
    return False


def _load_records(path: Path) -> List[Dict[str, Any]]:
    """Lee el JSON canonico con etiquetas legibles."""
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"Se esperaba una lista en {path}, llego {type(data)}")
    return data


_catalog: Optional[Catalog] = None


def get_catalog() -> Catalog:
    """Singleton. Construye el catalogo en la primera llamada."""
    global _catalog
    if _catalog is None:
        path = get_settings().extracted_json_resolved
        if not path.exists():
            raise FileNotFoundError(
                f"No encuentro el JSON canonico en {path}. "
                "Comprueba EXTRACTED_JSON_PATH en .env."
            )
        _catalog = Catalog(_load_records(path))
    return _catalog


def reset_catalog() -> None:
    """Util para tests."""
    global _catalog
    _catalog = None
