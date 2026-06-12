"""
simple_store.py — Almacen de embeddings sin ChromaDB.

Reemplazo NumPy puro de ChromaDB. ChromaDB hace segfault con Python del
Microsoft Store en Windows al abrir el cliente desde threads de Streamlit.

Estructura en disco (en _STORE_DIR):
    embeddings.npy   - matriz (N, D) float32 con vectores L2-normalizados
    records.json     - lista de N dicts con metadata por ISIN
    meta.json        - {provider, model, dim, count, ts}

API publica:
    save(records, vectors, info)   -> persiste el indice
    load() -> (vectors, records, info) | None si no existe
    query(qvec, top_k, filters)    -> [{ISIN, score, ...metadata}, ...]
    status()                       -> dict con info del indice
"""

from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np


# Carpeta fuera de OneDrive para evitar conflictos de sync.
_DEFAULT_STORE = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
    "cnmv_extractor", "store",
)
_STORE_DIR = Path(os.environ.get("STORE_DIR", _DEFAULT_STORE))


def _paths() -> Tuple[Path, Path, Path]:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)
    return (
        _STORE_DIR / "embeddings.npy",
        _STORE_DIR / "records.json",
        _STORE_DIR / "meta.json",
    )


def _normalize(vectors: np.ndarray) -> np.ndarray:
    """Normaliza L2 por fila para que cosine = dot."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def save(records: List[Dict[str, Any]],
         vectors: List[List[float]],
         info: Dict[str, Any]) -> Dict[str, Any]:
    """Persiste el indice. Devuelve estadisticas."""
    if len(records) != len(vectors):
        raise ValueError(
            f"records ({len(records)}) y vectors ({len(vectors)}) "
            f"no tienen la misma longitud"
        )
    arr = np.asarray(vectors, dtype=np.float32)
    arr = _normalize(arr)
    emb_path, rec_path, meta_path = _paths()
    np.save(emb_path, arr)
    rec_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta = {
        **info,
        "count": len(records),
        "dim": int(arr.shape[1]) if arr.size else 0,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return meta


def load() -> Optional[Tuple[np.ndarray, List[Dict[str, Any]], Dict[str, Any]]]:
    """Carga el indice. Devuelve None si no existe."""
    emb_path, rec_path, meta_path = _paths()
    if not (emb_path.exists() and rec_path.exists() and meta_path.exists()):
        return None
    vectors = np.load(emb_path)
    records = json.loads(rec_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return vectors, records, meta


def status() -> Dict[str, Any]:
    """Estado del indice sin cargar en RAM los embeddings."""
    emb_path, rec_path, meta_path = _paths()
    if not meta_path.exists():
        return {"error": "Sin colección indexada"}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        size_kb = (emb_path.stat().st_size + rec_path.stat().st_size) // 1024
        return {**meta, "size_kb": size_kb, "path": str(_STORE_DIR)}
    except Exception as e:
        return {"error": str(e)}


def _passes_filter(rec: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    if not filters:
        return True
    for k, v in filters.items():
        rv = rec.get(k)
        if isinstance(v, list):
            if rv not in v:
                return False
        else:
            if rv != v:
                return False
    return True


def query(qvec: List[float],
          top_k: int = 5,
          filters: Optional[Dict[str, Any]] = None,
          ) -> List[Dict[str, Any]]:
    """Busca top-K por cosine similarity. Cada resultado incluye el record
    completo + claves _similarity y _document (politica integra)."""
    loaded = load()
    if loaded is None:
        return []
    vectors, records, _ = loaded
    q = np.asarray(qvec, dtype=np.float32)
    qn = q / max(np.linalg.norm(q), 1e-12)
    # cosine = dot product (todos normalizados)
    sims = vectors @ qn

    # Filtros por metadata
    if filters:
        mask = np.array(
            [_passes_filter(r, filters) for r in records], dtype=bool
        )
        sims_filtered = np.where(mask, sims, -np.inf)
    else:
        sims_filtered = sims

    # top-K
    k = min(top_k, int(np.isfinite(sims_filtered).sum()))
    if k == 0:
        return []
    idxs = np.argsort(-sims_filtered)[:k]

    out = []
    for i in idxs:
        i = int(i)
        rec = dict(records[i])
        rec["_similarity"] = float(sims[i])
        out.append(rec)
    return out


# Diagnostico CLI rapido
def main() -> int:
    s = status()
    print(json.dumps(s, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
