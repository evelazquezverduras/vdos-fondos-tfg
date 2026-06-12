"""
openai_client.py — Cliente OpenAI para clasificacion P05/P06.

Misma interfaz que GeminiClassifier (drop-in replacement). Comparte la
cache JSON con el cliente Gemini para no duplicar llamadas cuando se
cambia de proveedor.

Modos:
  - 'real':    necesita OPENAI_API_KEY. Hace llamadas reales.
  - 'dry':     no llama. Imprime el prompt en stderr para inspeccion.

Modelo por defecto: gpt-4o-mini (rapido, barato, ~$0.15/$0.60 por M tokens).
Usa Structured Outputs (response_format=json_schema) para garantizar que
la respuesta es JSON valido y que P05/P06 estan en la lista de etiquetas
permitidas (sin hallucinations de categorias inventadas).
"""

from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_CACHE_DIR = Path(__file__).resolve().parent / ".cache"
_CACHE_FILE = _CACHE_DIR / "llm_classify.json"


def _cache_key(num_cnmv: Optional[str], compartimento: Optional[str]) -> str:
    """Misma clave que gemini_client para compartir cache."""
    return f"{(num_cnmv or '').strip()}|{(compartimento or '').strip()}"


def _load_cache() -> Dict[str, Dict[str, Any]]:
    if not _CACHE_FILE.exists():
        return {}
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Dict[str, Any]]) -> None:
    """Guarda la cache con escritura atomica + reintentos.

    OneDrive bloquea archivos durante la sincronizacion. Si write_text
    falla con PermissionError, reintenta hasta 5 veces con backoff.
    Si finalmente no puede, lo reporta a stderr pero NO levanta excepcion
    para no matar el proceso de extraccion (la cache es opcional, el
    progreso ya guardado se conserva en memoria)."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    content = json.dumps(cache, ensure_ascii=False, indent=2)
    tmp = _CACHE_FILE.with_suffix(".json.tmp")

    last_err = None
    for attempt in range(5):
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, _CACHE_FILE)
            return
        except (PermissionError, OSError) as e:
            last_err = e
            time.sleep(0.5 * (2 ** attempt))  # 0.5, 1, 2, 4, 8 s
    # No mata el proceso: solo avisa.
    print(f"[openai-cache WARN] no pude guardar cache tras 5 intentos: "
          f"{last_err}. Sigo sin guardar.", file=sys.stderr)


class OpenAIClassifier:
    """Cliente fino que envuelve el SDK de OpenAI con cache.

    Uso:
        oc = OpenAIClassifier(model="gpt-4o-mini", dry_run=False)
        p05, p06 = oc.classify(prompt, num_cnmv="12345", compartimento="ABC",
                               p05_labels=[...], p06_labels=[...])
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        dry_run: bool = False,
        api_key: Optional[str] = None,
        save_every: int = 20,
    ):
        self.model_name = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.dry_run = dry_run or not self.api_key
        self._cache = _load_cache()
        self._client = None  # lazy init
        self._save_every = max(1, int(save_every))
        self._pending = 0
        # Flush al salir del proceso, aunque sea por excepcion.
        import atexit
        atexit.register(self.flush)

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "Falta dependencia 'openai'. Instala con: pip install openai"
            ) from e
        self._client = OpenAI(api_key=self.api_key)

    def classify(
        self,
        prompt: str,
        num_cnmv: Optional[str],
        compartimento: Optional[str],
        p05_labels: List[str],
        p06_labels: List[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Devuelve (p05_label, p06_label) o (None, None) en dry/fallo."""
        key = _cache_key(num_cnmv, compartimento)
        if key in self._cache:
            entry = self._cache[key]
            return entry.get("P05"), entry.get("P06")

        if self.dry_run:
            print(f"[dry-run] num_cnmv={num_cnmv} comp={compartimento!r} "
                  f"prompt_chars={len(prompt)}", file=sys.stderr)
            return None, None

        self._ensure_client()
        # JSON Schema con enum para garantizar etiquetas validas.
        schema = {
            "type": "object",
            "properties": {
                "P05": {"type": "string", "enum": list(p05_labels)},
                "P06": {"type": "string", "enum": list(p06_labels)},
            },
            "required": ["P05", "P06"],
            "additionalProperties": False,
        }

        try:
            resp = self._client.chat.completions.create(
                model=self.model_name,
                temperature=0.0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "fund_classification",
                        "strict": True,
                        "schema": schema,
                    },
                },
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            p05 = data.get("P05")
            p06 = data.get("P06")
        except Exception as e:
            # Fallback: si el modelo no soporta json_schema (ej. version vieja),
            # probamos con json_object normal y validamos manualmente.
            try:
                resp = self._client.chat.completions.create(
                    model=self.model_name,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.choices[0].message.content or "{}"
                data = json.loads(raw)
                p05 = data.get("P05") if data.get("P05") in p05_labels else None
                p06 = data.get("P06") if data.get("P06") in p06_labels else None
            except Exception as e2:
                print(f"[openai ERROR] {e2}", file=sys.stderr)
                return None, None

        self._cache[key] = {
            "P05": p05, "P06": p06,
            "model": self.model_name,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._pending += 1
        if self._pending >= self._save_every:
            _save_cache(self._cache)
            self._pending = 0
        return p05, p06

    def flush(self) -> None:
        """Fuerza el guardado de la cache (atexit lo invoca al salir)."""
        if self._pending > 0:
            _save_cache(self._cache)
            self._pending = 0

    def stats(self) -> Dict[str, int]:
        return {"cache_size": len(self._cache)}
