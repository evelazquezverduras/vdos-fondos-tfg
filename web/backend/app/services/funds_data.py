"""Servicio de acceso a la BD SQLite del Comparador.

Encapsula todas las queries sobre `funds.sqlite` (metadata + historico VL) y
las cruza con el catalogo del JSON canon (los 447 fondos con folleto CNMV) para
enriquecer la ficha con P00/P05/P06/COMENT cuando esten disponibles.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import get_settings
from .catalog import get_catalog

# Permitir importar rag/labels del extractor para traducir P00/P05/P06 a etiqueta.
_EXTRACTOR_DIR = Path(__file__).resolve().parents[4] / "extractor_cnmv"
if str(_EXTRACTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTRACTOR_DIR))


# ---------------------------------------------------------------------------
# Conexion SQLite (read-only, compartida)
# ---------------------------------------------------------------------------
_DB_CACHE: sqlite3.Connection | None = None


def _db_path() -> Path:
    """Ruta absoluta a la BD generada por build_db.py.

    funds_data.py vive en tfg/web/backend/app/services/, por lo que
    parents[3] = tfg/web/.
    """
    web_dir = Path(__file__).resolve().parents[3]
    return web_dir / "data" / "funds.sqlite"


def get_db() -> sqlite3.Connection:
    """Devuelve una conexion read-only a la BD. Singleton."""
    global _DB_CACHE
    if _DB_CACHE is None:
        path = _db_path()
        if not path.exists():
            raise FileNotFoundError(
                f"No encuentro {path}. Corre `python backend/scripts/build_db.py`."
            )
        uri = f"file:{path.as_posix()}?mode=ro"
        _DB_CACHE = sqlite3.connect(uri, uri=True, check_same_thread=False)
        _DB_CACHE.row_factory = sqlite3.Row
    return _DB_CACHE


def reset_db() -> None:
    """Para tests: cerrar la conexion cacheada."""
    global _DB_CACHE
    if _DB_CACHE is not None:
        _DB_CACHE.close()
        _DB_CACHE = None


# ---------------------------------------------------------------------------
# Busqueda y filtros
# ---------------------------------------------------------------------------
def _brochure_isins() -> set[str]:
    """Set de ISINs presentes en el JSON canonico (los 447 con folleto)."""
    return set(get_catalog().by_isin.keys())


@lru_cache(maxsize=1)
def filter_options() -> dict[str, Any]:
    """Tipos, gestoras y CONTEOS reales para alimentar los selectores y los
    textos del frontend (asi las cifras nunca se hardcodean ni se desfasan)."""
    conn = get_db()
    tipos = [r[0] for r in conn.execute(
        "SELECT DISTINCT tipo FROM fund_meta WHERE tipo IS NOT NULL ORDER BY tipo"
    )]
    gestoras = [r[0] for r in conn.execute(
        "SELECT DISTINCT gestora FROM fund_meta WHERE gestora IS NOT NULL ORDER BY gestora"
    )]
    n_total = conn.execute("SELECT COUNT(*) FROM fund_meta").fetchone()[0]
    n_con_vl = conn.execute(
        "SELECT COUNT(DISTINCT isin) FROM vl_history"
    ).fetchone()[0]
    return {
        "tipos": tipos,
        "gestoras": gestoras,
        "n_total": int(n_total),
        "n_con_vl": int(n_con_vl),
    }


def search_funds(
    q: str | None = None,
    tipo: str | None = None,
    gestora: str | None = None,
    only_with_brochure: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Busqueda libre por ISIN, nombre o gestora.

    Match: case-insensitive contains. Si q es None, devuelve los primeros N
    despues de aplicar filtros."""
    conn = get_db()
    clauses: list[str] = []
    params: list[Any] = []

    if q and q.strip():
        # Buscamos el texto completo en una sola pasada con UPPER LIKE.
        # SQLite es case-insensitive para ASCII por defecto en LIKE, pero
        # algunos nombres tienen tildes que LIKE no normaliza. Forzamos
        # UPPER en ambos lados para ISIN/nombre/gestora.
        clauses.append(
            "(UPPER(isin) LIKE ? OR UPPER(nombre) LIKE ? OR UPPER(gestora) LIKE ?)"
        )
        like = f"%{q.strip().upper()}%"
        params.extend([like, like, like])

    if tipo:
        clauses.append("tipo = ?")
        params.append(tipo)

    if gestora:
        clauses.append("gestora = ?")
        params.append(gestora)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT isin, nombre, gestora, tipo FROM fund_meta {where} "
        f"ORDER BY nombre LIMIT ?"
    )
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()

    brochure = _brochure_isins() if only_with_brochure else None
    out: list[dict[str, Any]] = []
    for r in rows:
        has = r["isin"] in _brochure_isins()
        if only_with_brochure and not has:
            continue
        out.append({
            "isin": r["isin"],
            "nombre": r["nombre"],
            "gestora": r["gestora"],
            "tipo": r["tipo"],
            "has_brochure": has,
        })
    return out


# ---------------------------------------------------------------------------
# Detalle / ficha
# ---------------------------------------------------------------------------
def get_meta(isin: str) -> dict[str, Any] | None:
    """Devuelve la fila completa de fund_meta para un ISIN, o None."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM fund_meta WHERE isin = ?", (isin,)
    ).fetchone()
    return dict(row) if row else None


def _descatalogado(meta: dict[str, Any]) -> bool:
    """Marcamos como descatalogado si fecha_snapshot tiene >365 dias."""
    fs = meta.get("fecha_snapshot")
    if not fs:
        return True
    try:
        d = datetime.strptime(fs, "%Y-%m-%d").date()
    except ValueError:
        return True
    return (date.today() - d).days > 365


def _brochure_for(isin: str) -> dict[str, Any] | None:
    """Si el fondo esta en el JSON canon, extrae P00/P05/P06/COMENT/GARANT
    traducidos a etiqueta legible."""
    rec = get_catalog().by_isin.get(isin)
    if not rec:
        return None

    try:
        from rag.labels import code_to_label  # type: ignore
    except Exception:
        code_to_label = lambda var, code: code  # noqa: E731

    def _label(var: str, val: Any) -> str | None:
        if not val:
            return None
        if isinstance(val, str) and val.startswith(f"{var}_"):
            return code_to_label(var, val) or val
        return str(val)

    return {
        "p00_label": _label("P00", rec.get("P00")),
        "p05_label": _label("P05", rec.get("P05")),
        "p06_label": _label("P06", rec.get("P06")),
        "coment": rec.get("COMENT") or None,
        "garant": int(rec["GARANT"]) if rec.get("GARANT") is not None else None,
    }


def build_fund_detail(isin: str, max_drawdown: float | None = None) -> dict[str, Any] | None:
    """Compone el dict que satisface FundDetail. Recibe max_drawdown ya
    calculado desde el historico del rango (opcional)."""
    meta = get_meta(isin)
    if not meta:
        return None

    fees = {
        "com_gestion": meta.get("com_gestion"),
        "com_depositario": meta.get("com_depositario"),
        "com_reembolso": meta.get("com_reembolso"),
        "com_total": meta.get("com_total"),
        "retrocesion": meta.get("retrocesion"),
    }
    returns_keys = [
        "r1d", "r1s", "r1m", "r3m", "r6m", "r1a", "r2a", "r3a", "r5a", "rinicio",
        "ra", "ra1", "ra2", "ra3", "ra4", "ra5", "ra6",
        "ytd1", "ytd3", "ytd5",
    ]
    returns = {k: meta.get(k) for k in returns_keys}
    risk = {
        "volatilidad": meta.get("volatilidad"),
        "sharpe": meta.get("sharpe"),
        "ratio_info": meta.get("ratio_info"),
        "tracking_error": meta.get("tracking_error"),
        "alfa": meta.get("alfa"),
        "beta": meta.get("beta"),
        "r_cuadrado": meta.get("r_cuadrado"),
        "max_drawdown": max_drawdown,
    }
    quartiles = {
        k: meta.get(k)
        for k in ("qr1m", "qr3m", "qr1a", "qr3a", "qr5a", "prr1a", "prr3a", "prr5a")
    }
    structure = {
        "vl": meta.get("vl"),
        "patrimonio_miles": meta.get("patrimonio_miles"),
        "participaciones": meta.get("participaciones"),
        "fecha_registro": meta.get("fecha_registro"),
        "fecha_snapshot": meta.get("fecha_snapshot"),
        "aportacion_minima": meta.get("aportacion_minima"),
        "divisa": meta.get("divisa"),
    }

    return {
        "isin": meta["isin"],
        "nombre": meta.get("nombre") or "",
        "gestora": meta.get("gestora"),
        "depositaria": meta.get("depositaria"),
        "tipo": meta.get("tipo"),
        "cat_macro": meta.get("cat_macro"),
        "descatalogado": _descatalogado(meta),
        "fees": fees,
        "returns": returns,
        "risk": risk,
        "quartiles": quartiles,
        "structure": structure,
        "brochure": _brochure_for(meta["isin"]),
    }


# ---------------------------------------------------------------------------
# Historico VL
# ---------------------------------------------------------------------------
def _resolve_range(desde: str | None, hasta: str | None) -> tuple[str, str]:
    """Defaults: hasta = ultima fecha disponible, desde = 5 anos atras."""
    conn = get_db()
    if not hasta:
        row = conn.execute("SELECT MAX(fecha) AS m FROM vl_history").fetchone()
        hasta = row["m"] if row and row["m"] else date.today().isoformat()
    if not desde:
        end = datetime.strptime(hasta, "%Y-%m-%d").date()
        desde = (end - timedelta(days=5 * 365)).isoformat()
    return desde, hasta


def get_timeseries(
    isin: str,
    desde: str | None = None,
    hasta: str | None = None,
) -> dict[str, Any]:
    """Devuelve la serie historica de VL+patrimonio para un ISIN en un rango."""
    desde, hasta = _resolve_range(desde, hasta)
    conn = get_db()
    rows = conn.execute(
        """
        SELECT fecha, vl, patrimonio
        FROM vl_history
        WHERE isin = ? AND fecha BETWEEN ? AND ?
        ORDER BY fecha ASC
        """,
        (isin, desde, hasta),
    ).fetchall()
    puntos = [
        {"fecha": r["fecha"], "vl": r["vl"], "patrimonio": r["patrimonio"]}
        for r in rows
    ]
    return {"isin": isin, "desde": desde, "hasta": hasta, "puntos": puntos}


def get_raw_series(
    isin: str,
    desde: str,
    hasta: str,
) -> list[tuple[str, float]]:
    """Devuelve [(fecha, vl), ...] crudo para los calculos numericos."""
    conn = get_db()
    rows = conn.execute(
        """
        SELECT fecha, vl FROM vl_history
        WHERE isin = ? AND fecha BETWEEN ? AND ?
        ORDER BY fecha ASC
        """,
        (isin, desde, hasta),
    ).fetchall()
    return [(r["fecha"], r["vl"]) for r in rows]
