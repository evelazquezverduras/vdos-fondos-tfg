"""Servicios del Estudio comparativo VDOS vs ChatGPT.

Maneja la carga de perfiles canonicos, la persistencia en disco de las
recomendaciones generadas (ChatGPT pegado + Asesor ejecutado), y la
generacion del prompt que el gestor copiara a chat.openai.com.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
_SERVICES_DIR = Path(__file__).resolve().parent
_WEB_DIR = _SERVICES_DIR.parents[2]
_ESTUDIO_DIR = _WEB_DIR / "data" / "estudio"
_PERFILES_FILE = _ESTUDIO_DIR / "perfiles.json"
_CHATGPT_DIR = _ESTUDIO_DIR / "chatgpt"
_ASESOR_DIR = _ESTUDIO_DIR / "asesor"

for d in (_CHATGPT_DIR, _ASESOR_DIR):
    d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Perfiles canonicos
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_perfiles() -> List[Dict[str, Any]]:
    """Carga los 5 perfiles canonicos definidos en perfiles.json."""
    if not _PERFILES_FILE.exists():
        raise FileNotFoundError(f"No encuentro {_PERFILES_FILE}")
    return json.loads(_PERFILES_FILE.read_text(encoding="utf-8"))


def get_perfil(perfil_id: str) -> Optional[Dict[str, Any]]:
    return next((p for p in get_perfiles() if p["id"] == perfil_id), None)


# ---------------------------------------------------------------------------
# Prompt para chat.openai.com
# ---------------------------------------------------------------------------
_PROMPT_TEMPLATE = """Eres un asesor financiero senior que ayuda a gestores de banca privada \
española a seleccionar fondos de inversión NACIONALES (depositados en CNMV) \
para clientes minoristas, respetando MiFID II.

Recomienda entre 3 y 5 fondos de inversión NACIONALES ESPAÑOLES (registrados \
en la CNMV, ISIN español que empieza por "ES") para el siguiente cliente:

=== PERFIL DEL CLIENTE ===
{perfil_block}

Adecua el riesgo al perfil del cliente:
- Conservador: RF/monetarios/garantizados predominantes.
- Moderado: mixto / RV diversificada.
- Agresivo: RV internacional, sectores tematicos, emergentes.

Casa el horizonte temporal con el plazo del fondo. Considera las preferencias \
sectoriales y geograficas. Si pide ESG/etico, prioriza fondos con criterios ASG.

=== FORMATO DE RESPUESTA ===
Responde UNICAMENTE con un objeto JSON valido, sin markdown ni bloques de codigo, \
con la forma exacta:
{{
  "resumen_ejecutivo": "...",
  "fondos_recomendados": [
    {{
      "isin": "ESXXXXXXXXXX",
      "nombre": "Nombre exacto del fondo",
      "peso_cartera_pct": 30,
      "justificacion": "Por que este fondo encaja con este cliente."
    }}
  ],
  "cartera_modelo": {{
    "descripcion": "Distribucion global propuesta",
    "asignacion": [
      {{"bloque": "RV Internacional", "peso_pct": 40, "isins": ["ES..."]}}
    ]
  }},
  "riesgos_y_advertencias": "Riesgos relevantes para este cliente."
}}

Los pesos deben sumar 100. Entre 3 y 5 fondos. Solo fondos NACIONALES (ISIN ES...).
"""


def _format_perfil_block(profile: Dict[str, Any]) -> str:
    """Convierte el dict del perfil a texto plano para el prompt."""
    lines: List[str] = []
    keymap = [
        ("Nombre", "nombre"),
        ("Edad", "edad"),
        ("Pais", "pais"),
        ("Renta anual", "renta"),
        ("Capital disponible (EUR)", "capital"),
        ("Aportacion mensual (EUR)", "aportacion_mensual"),
        ("Horizonte temporal", "horizonte"),
        ("Perfil de riesgo", "perfil_riesgo"),
        ("Sectores preferidos", "sectores"),
        ("Regiones preferidas", "regiones"),
        ("Exclusiones ESG", "excluir"),
        ("Notas del gestor", "notas"),
    ]
    for label, key in keymap:
        v = profile.get(key)
        if v in (None, "", [], 0):
            continue
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        lines.append(f"- {label}: {v}")
    return "\n".join(lines)


def build_prompt_for_chatgpt(perfil: Dict[str, Any]) -> str:
    """Prompt listo para copiar a chat.openai.com."""
    block = _format_perfil_block(perfil["profile"])
    extra = ""
    if perfil.get("gestor_banco"):
        extra = (
            f"\n\nContexto adicional: el gestor pertenece a {perfil['gestor_banco']}. "
            "Si encuentras fondos adecuados de esa gestora, prioritzalos."
        )
    return _PROMPT_TEMPLATE.format(perfil_block=block) + extra


# ---------------------------------------------------------------------------
# Persistencia en disco
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _strip_code_fences(text: str) -> str:
    """Acepta JSON con o sin ```json ... ``` envolviendolo."""
    t = text.strip()
    # ```json ... ``` o ``` ... ```
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.DOTALL)
    if m:
        return m.group(1).strip()
    return t


def parse_chatgpt_paste(raw_text: str) -> Dict[str, Any]:
    """Intenta parsear el JSON que el gestor pego desde chat.openai.com.

    Si no es JSON valido, devuelve un dict con solo raw_text para que el
    frontend pueda mostrar el texto como esta. Nunca lanza."""
    cleaned = _strip_code_fences(raw_text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return {}


def save_chatgpt_response(
    perfil_id: str, raw_text: str, modelo: Optional[str] = None
) -> Dict[str, Any]:
    """Guarda la respuesta de ChatGPT en disco y devuelve el dict parseado."""
    parsed = parse_chatgpt_paste(raw_text)
    record = {
        "fuente": "chatgpt",
        "perfil_id": perfil_id,
        "modelo": modelo or "chatgpt-unknown",
        "timestamp": _now_iso(),
        "raw_text": raw_text,
        "resumen_ejecutivo": str(parsed.get("resumen_ejecutivo", "")),
        "fondos_recomendados": _normalize_fondos(parsed.get("fondos_recomendados") or []),
        "cartera_modelo": parsed.get("cartera_modelo"),
        "riesgos_y_advertencias": str(parsed.get("riesgos_y_advertencias", "")),
    }
    out = _CHATGPT_DIR / f"{perfil_id}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def save_asesor_response(perfil_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Persiste la respuesta del Asesor VDOS para un perfil."""
    record = {
        "fuente": "asesor_vdos",
        "perfil_id": perfil_id,
        "modelo": "gpt-4o-mini + catalogo CNMV",
        "timestamp": _now_iso(),
        "resumen_ejecutivo": str(raw.get("resumen_ejecutivo", "")),
        "fondos_recomendados": _normalize_fondos(raw.get("fondos_recomendados") or []),
        "cartera_modelo": raw.get("cartera_modelo"),
        "riesgos_y_advertencias": str(raw.get("riesgos_y_advertencias", "")),
    }
    out = _ASESOR_DIR / f"{perfil_id}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def _normalize_fondos(items: List[Any]) -> List[Dict[str, Any]]:
    """Normaliza a {isin, nombre, peso_cartera_pct, justificacion}."""
    out: List[Dict[str, Any]] = []
    for f in items:
        if not isinstance(f, dict):
            continue
        isin = str(f.get("isin") or "").strip().upper()
        if not isin:
            continue
        out.append({
            "isin": isin,
            "nombre": str(f.get("nombre") or "").strip(),
            "peso_cartera_pct": _to_float(f.get("peso_cartera_pct")),
            "justificacion": str(f.get("justificacion") or "").strip(),
        })
    return out


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_chatgpt(perfil_id: str) -> Optional[Dict[str, Any]]:
    p = _CHATGPT_DIR / f"{perfil_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def load_asesor(perfil_id: str) -> Optional[Dict[str, Any]]:
    p = _ASESOR_DIR / f"{perfil_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def delete_chatgpt(perfil_id: str) -> bool:
    p = _CHATGPT_DIR / f"{perfil_id}.json"
    if p.exists():
        p.unlink()
        return True
    return False
