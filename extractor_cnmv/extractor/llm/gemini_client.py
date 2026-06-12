"""
gemini_client.py — Cliente Gemini con cache persistente.

Cache:
  - Por (num_cnmv, compartimento) segun CLAUDE.md §4.
  - Archivo JSON en extractor_cnmv/extractor/llm/.cache/llm_classify.json
  - Lazy load + write-through.

Modos:
  - 'real':    necesita GEMINI_API_KEY en el entorno. Hace llamadas reales.
  - 'dry':     no llama. Devuelve (None, None) e imprime el prompt en stderr
               para que se pueda inspeccionar antes de gastar API calls.

Modelo por defecto: gemini-2.5-flash (rapido, barato).
"""

from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any


_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
_CACHE_FILE = _CACHE_DIR / "llm_classify.json"


def _cache_key(num_cnmv: Optional[str], compartimento: Optional[str]) -> str:
    """Clave estable. Si no hay num_cnmv, usa el compartimento solo."""
    return f"{(num_cnmv or '').strip()}|{(compartimento or '').strip()}"


def _load_cache() -> Dict[str, Dict[str, Any]]:
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class GeminiClassifier:
    """Cliente fino que envuelve el SDK de Gemini con cache.

    Uso:
        gc = GeminiClassifier(model="gemini-2.5-flash", dry_run=False)
        p05, p06 = gc.classify(prompt, num_cnmv="12345", compartimento="ABC")
    """

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        dry_run: bool = False,
        api_key: Optional[str] = None,
    ):
        self.model_name = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        # dry_run efectivo: el caller fuerza, o no hay api_key
        self.dry_run = dry_run or not self.api_key
        self._cache = _load_cache()
        self._client = None  # init perezoso para no requerir SDK en dry-run

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise RuntimeError(
                "Falta dependencia 'google-generativeai'. "
                "Instala con: pip install google-generativeai"
            ) from e
        genai.configure(api_key=self.api_key)
        self._client = genai.GenerativeModel(self.model_name)

    def classify(
        self,
        prompt: str,
        num_cnmv: Optional[str],
        compartimento: Optional[str],
        p05_labels: list,
        p06_labels: list,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Devuelve (p05_label, p06_label) o (None, None) si dry-run / fallo."""
        key = _cache_key(num_cnmv, compartimento)
        if key in self._cache:
            entry = self._cache[key]
            return entry.get("P05"), entry.get("P06")

        if self.dry_run:
            print(f"[dry-run] num_cnmv={num_cnmv} comp={compartimento!r} "
                  f"prompt_chars={len(prompt)}", file=sys.stderr)
            return None, None

        self._ensure_client()
        import google.generativeai as genai
        # Forzar JSON con response_schema constrained a las etiquetas validas.
        schema = {
            "type": "object",
            "properties": {
                "P05": {"type": "string", "enum": list(p05_labels)},
                "P06": {"type": "string", "enum": list(p06_labels)},
            },
            "required": ["P05", "P06"],
        }
        gen_cfg = genai.types.GenerationConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.0,
        )
        try:
            resp = self._client.generate_content(prompt, generation_config=gen_cfg)
            raw = resp.text or "{}"
            data = json.loads(raw)
            p05 = data.get("P05")
            p06 = data.get("P06")
        except Exception as e:
            print(f"[gemini ERROR] {e}", file=sys.stderr)
            return None, None

        self._cache[key] = {
            "P05": p05, "P06": p06,
            "model": self.model_name,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        _save_cache(self._cache)
        return p05, p06

    def stats(self) -> Dict[str, int]:
        return {"cache_size": len(self._cache)}
