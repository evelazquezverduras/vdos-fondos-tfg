"""codigos_2026.py -- Catalogo canonico de codigos para fondos NACIONALES.

----------------------------------------------------------------------------
NOTA DE VERSION SANEADA
Los codigos internos reales del proveedor (mapeos codigo <-> etiqueta para
P00/P01/P05/P06 y las reglas de combinacion por categoria P20) se han
sustituido por codigos NEUTROS de EJEMPLO. En la version interna estos
catalogos se cargan desde hojas de calculo y CSV propietarios que aqui se
omiten. La API publica del modulo se conserva intacta.
----------------------------------------------------------------------------

API publica:
  catalogo_2026() -> dict {var -> {codigo: etiqueta}}
  etiquetas_2026() -> dict {var -> {etiqueta_normalizada: codigo}}
  reglas_por_p20(p20) -> list[dict]  combinaciones P00/P05/P06 validas
  codigos_p20_nacionales() -> list[str]   las categorias P20 (CNMV)
  codigos_p01_nacionales() -> dict {codigo: etiqueta}
"""

from __future__ import annotations
import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Categorias P20 (vocacion CNMV) para fondos nacionales.
# (En la version interna cada una mapea a un CSV de reglas propietario.)
# ---------------------------------------------------------------------------
P20_NACIONALES: List[str] = [
    "RF EURO", "RF EURO CORTO PLAZO", "RF INTERNACIONAL",
    "RF MIXTA EURO", "RF MIXTA INTERNACIONAL",
    "RV MIXTA EURO", "RV MIXTA INTERNACIONAL", "RV EURO", "RV INTERNACIONAL",
    "GARANTIZADO REND.FIJO", "GARANTIZADO REND.VAR.", "DE GARANTIA PARCIAL",
    "RETORNO ABSOLUTO", "IIC OBJETIVO DE RENTABILIDAD",
]


def codigos_p20_nacionales() -> List[str]:
    """Lista las categorias P20 (vocacion CNMV) para fondos nacionales."""
    return list(P20_NACIONALES)


# ---------------------------------------------------------------------------
# Formas juridicas P01 (codigos NEUTROS de ejemplo).
# ---------------------------------------------------------------------------
P01_NACIONALES: Dict[str, str] = {
    "P01_FI": "FONDO DE INVERSION (FI)",
    "P01_FII": "FONDO DE INVERSION INMOBILIARIA (FII)",
    "P01_ETF": "FONDO COTIZADO / ETF",
    "P01_IDX": "FONDO INDICE",
    "P01_FIL": "FONDO DE INVERSION LIBRE (FIL)",
}


def codigos_p01_nacionales() -> Dict[str, str]:
    """Devuelve los codigos P01 de ejemplo validos para fondos nacionales."""
    return dict(P01_NACIONALES)


def es_p01_nacional(codigo: str) -> bool:
    return codigo in P01_NACIONALES


# ---------------------------------------------------------------------------
# Catalogo de ejemplo {var: {codigo: etiqueta}}.
# Reemplaza la carga del catalogo propietario.
# ---------------------------------------------------------------------------
_CATALOGO_EJEMPLO: Dict[str, Dict[str, str]] = {
    "P00": {
        "RF_EURO": "RENTA FIJA EURO",
        "RV_EURO": "RENTA VARIABLE EURO",
        "RV_INTL": "RENTA VARIABLE INTERNACIONAL",
        "MIXTO": "MIXTO",
        "GARANT_RF": "GARANTIZADO RENTA FIJA",
        "GLOBAL": "GLOBAL",
        "SIN_CLASIFICAR": "SIN CLASIFICAR",
    },
    "P01": dict(P01_NACIONALES),
    "P05": {
        "P05_EUR": "ZONA EURO / EUR", "P05_USA": "USA / USD",
        "P05_GLB": "GLOBAL / EUR", "P05_EMG": "EMERGENTES / MULTIDIVISA",
        "P05_SC": "SIN CLASIFICAR",
    },
    "P06": {
        "P06_RF": "RENTA FIJA", "P06_RV": "RENTA VARIABLE",
        "P06_TEC": "TECNOLOGIA", "P06_GLB": "GLOBAL", "P06_SC": "SIN CLASIFICAR",
    },
}


def _normaliza(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def catalogo_2026() -> Dict[str, Dict[str, str]]:
    """Devuelve el catalogo {var: {codigo: etiqueta}} (version de ejemplo)."""
    return {k: dict(v) for k, v in _CATALOGO_EJEMPLO.items()}


@lru_cache(maxsize=1)
def etiquetas_2026() -> Dict[str, Dict[str, str]]:
    """Indice inverso {var: {etiqueta_normalizada: codigo}}."""
    out: Dict[str, Dict[str, str]] = {"P00": {}, "P01": {}, "P05": {}, "P06": {}}
    for var, mapping in _CATALOGO_EJEMPLO.items():
        for code, label in mapping.items():
            out[var][_normaliza(label)] = code
    return out


def codigo_de_etiqueta(var: str, etiqueta: str) -> Optional[str]:
    if not etiqueta:
        return None
    return etiquetas_2026().get(var, {}).get(_normaliza(etiqueta))


def etiqueta_de_codigo(var: str, codigo: str) -> Optional[str]:
    if not codigo:
        return None
    return catalogo_2026().get(var, {}).get(codigo)


def es_codigo_valido(var: str, codigo: str) -> bool:
    return codigo in catalogo_2026().get(var, {})


def reglas_por_p20(p20: str) -> List[Dict[str, Any]]:
    """En la version interna devuelve las combinaciones P00/P05/P06 validas
    para la categoria P20 (cargadas de CSV propietarios). En esta version
    saneada no se incluyen esas reglas, por lo que devuelve []."""
    return []


def resumen_carga() -> Dict[str, int]:
    cat = catalogo_2026()
    return {
        "P00_codes": len(cat.get("P00", {})),
        "P01_codes_nacionales": len(P01_NACIONALES),
        "P05_codes": len(cat.get("P05", {})),
        "P06_codes": len(cat.get("P06", {})),
        "p20_categorias": len(P20_NACIONALES),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(resumen_carga(), indent=2, ensure_ascii=False))
