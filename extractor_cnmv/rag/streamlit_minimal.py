"""
streamlit_minimal.py — Diagnostico minimalista.

Lanzar:
    python -m streamlit run rag\streamlit_minimal.py

Cada paso escribe en debug.log. Si el proceso muere, el ultimo registro
del log dira que pieza es la culpable.
"""

from __future__ import annotations
import sys
import os
import time
import traceback
from pathlib import Path

# Permitir import del paquete
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

# Log fisico (no depende de streamlit)
LOG = _HERE.parent.parent / "debug.log"


def _log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')}  {msg}\n"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


_log("=== START ===")

try:
    _log("import streamlit")
    import streamlit as st
    _log(f"streamlit {st.__version__}")

    _log("set_page_config")
    st.set_page_config(page_title="Min", layout="wide")
    st.title("CNMV — diagnóstico")

    _log("import json")
    import json
    _log("ok json")

    DEFAULT_JSON = Path(__file__).resolve().parent.parent.parent / "pdfs_extracted.json"
    st.write(f"JSON: `{DEFAULT_JSON}`")
    _log(f"json path = {DEFAULT_JSON}")

    if not DEFAULT_JSON.exists():
        st.error("No encuentro el JSON")
        _log("ERROR: no json")
        st.stop()

    _log("load json")
    records = json.loads(DEFAULT_JSON.read_text(encoding="utf-8"))
    _log(f"loaded {len(records)} ISINs")
    st.success(f"PASO 1 OK — {len(records)} ISINs cargados")

    _log("import openai")
    from openai import OpenAI
    _log("ok openai import")

    if not os.environ.get("OPENAI_API_KEY"):
        st.warning("PASO 2 SKIP — sin OPENAI_API_KEY en entorno")
        _log("no OPENAI_API_KEY")
    else:
        _log("init OpenAI client")
        _client = OpenAI()
        _log("OpenAI client OK")
        st.success("PASO 2 OK — cliente OpenAI inicializado")

    _log("import chromadb")
    import chromadb
    from chromadb.config import Settings
    _log(f"chromadb {chromadb.__version__}")

    chroma_dir = os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
        "cnmv_extractor", "chromadb",
    )
    _log(f"chroma_dir = {chroma_dir}")
    st.write(f"ChromaDB dir: `{chroma_dir}`")

    _log("create PersistentClient")
    client = chromadb.PersistentClient(
        path=chroma_dir,
        settings=Settings(anonymized_telemetry=False),
    )
    _log("PersistentClient OK")
    st.success("PASO 3 OK — ChromaDB cliente")

    _log("get_collection")
    try:
        coll = client.get_collection("cnmv_funds")
        _log(f"collection count = {coll.count()}")
        st.success(f"PASO 4 OK — colección con {coll.count()} docs")
    except Exception as e:
        _log(f"collection MISS: {e}")
        st.warning(f"PASO 4 SKIP — no hay colección: {e}")

    st.divider()
    st.write("Si llegas a leer esto y la página NO se cierra, todo el "
             "stack funciona. Revisa `debug.log` en la raíz del repo "
             "para ver el orden de los pasos.")
    _log("=== END OK ===")

except Exception as e:
    _log(f"EXCEPTION: {e}")
    _log(traceback.format_exc())
    try:
        st.error(f"Error: {e}")
        st.code(traceback.format_exc())
    except Exception:
        pass
