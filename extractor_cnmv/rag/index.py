"""
index.py — Indexador semantico sobre el JSON literal (fase 1+2+3).

Reemplazo de ChromaDB por un almacen NumPy puro (rag.simple_store).
ChromaDB crashea con segfault desde el thread de Streamlit en Python del
Microsoft Store, por eso usamos un store basado solo en numpy + json.

Cada documento queda con:
  - documento embebido = bloque enriquecido (NFONDO + gestora + catalogos +
    politica)
  - record = registro completo (55 claves), para metadata y filtros

CLI:
    python -m rag.index ../pdfs_extracted.json
    python -m rag.index ../pdfs_extracted.json --reset
    python -m rag.index --status
    python -m rag.index --list-models
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List


def _bootstrap_env() -> None:
    """Carga .env desde rutas comunes y SOBREESCRIBE OPENAI_API_KEY /
    GEMINI_API_KEY si estan definidas en el .env. Esto evita problemas
    con claves antiguas persistidas en el entorno de Windows.
    """
    here = Path(__file__).resolve().parent       # tfg/extractor_cnmv/rag
    tfg_dir = here.parents[1]                    # tfg/
    candidates = [
        Path.cwd() / ".env",
        tfg_dir / "web" / ".env",
        tfg_dir / ".env",
        tfg_dir / "extractor_cnmv" / ".env",
    ]
    override_keys = {"OPENAI_API_KEY", "GEMINI_API_KEY"}
    for path in candidates:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if not k or not v:
                    continue
                if k in override_keys or k not in os.environ:
                    os.environ[k] = v
        except Exception:
            continue


_bootstrap_env()

from .embed import EmbeddingClient  # noqa: E402
from . import simple_store  # noqa: E402


_META_KEYS = (
    "ISIN", "NFONDO", "P02", "P11", "P20", "P00", "P05", "P06",
    "P01", "FCREC", "DMINR", "GARANT", "AUDITOR", "DIVISA",
    "COMIGEST", "SCOMIG", "COMIDEPO", "SCOMID",
    "COMIAPEX", "SCOMIA", "COMIREEX", "SCOMIR",
    "INFOREFB", "FVENGAR", "SVENGAR",
)


def _meta_for(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Subconjunto de metadata para el almacen."""
    out: Dict[str, Any] = {}
    for k in _META_KEYS:
        v = rec.get(k)
        if v is None:
            continue
        out[k] = v
    # Incluimos COMENT completo para que el chat tenga la politica.
    if rec.get("COMENT"):
        out["COMENT"] = rec["COMENT"]
    return out


def _build_document(rec: Dict[str, Any]) -> str:
    """Documento enriquecido por ISIN. Esto es lo que se embede."""
    parts = []
    isin = rec.get("ISIN", "")
    nfondo = rec.get("NFONDO", "")
    parts.append(f"ISIN: {isin}")
    parts.append(f"Nombre del fondo: {nfondo}")

    for label, key in (
        ("Gestora", "P02"), ("Depositario", "P11"), ("Auditor", "AUDITOR"),
        ("Tipo", "P01"),
        ("Categoría CNMV", "P20"), ("Categoría VDOS", "P00"),
        ("Región / divisa principal", "P05"),
        ("Sector / tipo de activo", "P06"),
    ):
        v = rec.get(key)
        if v:
            parts.append(f"{label}: {v}")

    if rec.get("GARANT") == 1:
        parts.append("Es un fondo GARANTIZADO.")
        for k in ("FVENGAR", "FINIGAR", "FCOMINI", "FCOMFIN", "PCOMER"):
            v = rec.get(k)
            if v:
                parts.append(f"  {k}: {v}")

    if rec.get("DMINR"):
        parts.append(f"Plazo indicativo: {rec['DMINR']}")

    inforefb = rec.get("INFOREFB")
    if inforefb and inforefb != "Sin Benchmark de Referencia":
        parts.append(f"Benchmark: {inforefb}")

    for k_lbl, k in (("Comisión de gestión", "SCOMIG"),
                     ("Comisión sobre resultados", "SCOMIRDO"),
                     ("Comisión depositario", "SCOMID"),
                     ("Comisión suscripción", "SCOMIA"),
                     ("Comisión reembolso", "SCOMIR")):
        v = rec.get(k)
        if v and v != "0,00%" and not str(v).startswith("0,00%"):
            parts.append(f"{k_lbl}: {v}")

    if rec.get("DIVISA"):
        parts.append(f"Divisa: {rec['DIVISA']}")

    coment = (rec.get("COMENT") or "").strip()
    if coment:
        parts.append("")
        parts.append("Política de inversión:")
        parts.append(coment)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# API de alto nivel
# ---------------------------------------------------------------------------
def index_json(json_path: str, reset: bool = False) -> Dict[str, Any]:
    """Lee el JSON, embede y persiste en simple_store. Devuelve stats."""
    data: List[Dict[str, Any]] = json.loads(
        Path(json_path).read_text(encoding="utf-8")
    )
    if not data:
        raise ValueError(f"{json_path}: JSON vacio")

    embedder = EmbeddingClient(provider="auto")
    info = embedder.info()
    print(f"Embeddings: provider={info['provider']} model={info['model']} "
          f"dim={info['dim']}", file=sys.stderr)

    if reset:
        from . import simple_store as _s
        emb_path, rec_path, meta_path = _s._paths()
        for p in (emb_path, rec_path, meta_path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        print("Almacen reseteado", file=sys.stderr)

    docs: List[str] = []
    records: List[Dict[str, Any]] = []
    for r in data:
        coment = (r.get("COMENT") or "").strip()
        if not coment:
            continue
        docs.append(_build_document(r))
        records.append(_meta_for(r))

    if not records:
        raise ValueError("Ningun registro con COMENT no vacio")

    print(f"Embedeando {len(records)} ISINs...", file=sys.stderr)
    vectors = embedder.embed(docs)

    stats = simple_store.save(records, vectors, info)
    print(f"OK: {stats['count']} documentos en el almacen ({stats.get('size_kb','?')} KB)",
          file=sys.stderr)
    return {"indexed": stats["count"], **info}


# Compatibilidad con codigo antiguo que importaba get_collection
def get_collection():
    """Compatibilidad: devuelve un placeholder. NO se usa con simple_store."""
    raise RuntimeError(
        "get_collection() ya no se usa. Migra a rag.simple_store.query()."
    )


# Para que rag.streamlit_app pueda mostrar la ruta
_CHROMA_DIR = simple_store._STORE_DIR  # alias compat


# ---------------------------------------------------------------------------
# Diagnostico (solo OpenAI ahora)
# ---------------------------------------------------------------------------
def list_models() -> int:
    if os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        client = OpenAI()
        print("--- Modelos OpenAI (filtrados a embeddings) ---")
        for m in client.models.list().data:
            if "embed" in m.id:
                print(f"  {m.id}")
        return 0
    print("ERROR: define OPENAI_API_KEY", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Indexa pdfs_extracted.json en simple_store (NumPy)."
    )
    p.add_argument("json_path", nargs="?", help="Ruta al JSON literal")
    p.add_argument("--reset", action="store_true",
                   help="Borra el almacen antes de indexar")
    p.add_argument("--status", action="store_true",
                   help="Muestra el estado del almacen")
    p.add_argument("--list-models", action="store_true",
                   help="Diagnostico: lista modelos disponibles")
    args = p.parse_args(argv)

    if args.list_models:
        return list_models()
    if args.status:
        print(json.dumps(simple_store.status(), ensure_ascii=False, indent=2))
        return 0
    if not args.json_path:
        p.print_help()
        return 1
    if not Path(args.json_path).exists():
        print(f"ERROR: no encuentro {args.json_path}", file=sys.stderr)
        return 1
    index_json(args.json_path, reset=args.reset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
