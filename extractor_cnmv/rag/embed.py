"""
embed.py — Wrapper de embeddings sobre OpenAI.

Por decision de la propietaria, el proyecto usa exclusivamente OpenAI para
embeddings. Modelo por defecto: 'text-embedding-3-small' (1536 dim).
Override via env var EMBED_MODEL si se quiere subir a 'text-embedding-3-large'.

Requiere OPENAI_API_KEY en el entorno.
"""

from __future__ import annotations
import os
from typing import List


_DEFAULT_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")

# Dimensiones por modelo OpenAI (los actuales).
_OPENAI_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class EmbeddingClient:
    """Cliente unificado sobre OpenAI. Sin fallbacks."""

    provider = "openai"

    def __init__(self, provider: str = "auto", model: str | None = None):
        # `provider` se conserva por compatibilidad con codigo previo, pero
        # solo se soporta 'openai'.
        if provider not in ("auto", "openai"):
            raise RuntimeError(
                f"Proveedor no soportado: {provider!r}. Solo 'openai'."
            )
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "Falta OPENAI_API_KEY en el entorno. PowerShell:\n"
                "  $env:OPENAI_API_KEY = 'sk-...'"
            )
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("Falta dependencia 'openai'") from e
        self._client = OpenAI()
        self.model = model or _DEFAULT_MODEL
        self.dim = _OPENAI_DIMS.get(self.model, 1536)

    def embed(self, texts: List[str], batch_size: int = 64) -> List[List[float]]:
        """Embebe una lista de textos en lotes para evitar limites de
        tokens por request de OpenAI (~ 8K tokens/texto, 300K/batch)."""
        if not texts:
            return []
        out: List[List[float]] = []
        n = len(texts)
        for i in range(0, n, batch_size):
            chunk = texts[i:i + batch_size]
            resp = self._client.embeddings.create(
                model=self.model, input=chunk,
            )
            out.extend(d.embedding for d in resp.data)
            # progreso minimal por stderr
            import sys as _sys
            _sys.stderr.write(
                f"\r  embed batch {min(i + batch_size, n)}/{n}"
            )
            _sys.stderr.flush()
        import sys as _sys
        _sys.stderr.write("\n")
        return out

    def embed_query(self, text: str) -> List[float]:
        """Embed para una sola query."""
        r = self._client.embeddings.create(model=self.model, input=[text])
        return r.data[0].embedding

    def info(self) -> dict:
        return {"provider": self.provider, "model": self.model, "dim": self.dim}
