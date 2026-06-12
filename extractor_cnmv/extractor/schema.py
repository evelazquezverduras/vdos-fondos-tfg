"""
schema.py — Definicion canonica del JSON de salida (55 claves, orden fijo).

Reglas consolidadas:
  - 1 registro plano por ISIN (PK absoluta).
  - Campos comunes al fondo / compartimento se replican en los N registros.
  - Tipos exactos: float para limites/comisiones (sin %), str para variables S*,
    int para flags (GARANT, HEDGEDVL, TIPONOT), null permitido solo donde
    se especifica.
"""

from __future__ import annotations
from collections import OrderedDict
from typing import Any

# ---------------------------------------------------------------------------
# Orden canonico de las 55 claves
# ---------------------------------------------------------------------------
KEYS_ORDER: list[str] = [
    # Base (12)
    "ISIN", "NFONDO", "NCFONDO", "FCREC",
    "P02", "P11", "AUDITOR",
    "P01", "P20", "P00", "P05", "P06",
    # Politica y Riesgo (5)
    "PRIESGOF", "COMENT", "INFOREFB", "DMINR", "GARANT",
    # Fechas Garantia (6, null si GARANT == 0)
    "SVENGAR", "FVENGAR", "FINIGAR", "FCOMINI", "FCOMFIN", "PCOMER",
    # Comercializacion y Minimos (10)
    "PERIODVLP", "DIVISA", "DIVIBASE", "TIPOPART",
    "APMIN", "UAPMIN", "SAPMIN",
    "MINIMANT", "UMINMANT", "VOLMAXP",
    # Comisiones y Descuentos (16)
    "COMIGEST", "SCOMIG",
    "COMIRDO", "SCOMIRDO",
    "COMIDEPO", "SCOMID",
    "COMIAPEX", "COMIAPEN", "SCOMIA", "SDESCA",
    "COMIREEX", "COMIREEN", "SCOMIR", "SDESCR",
    "COMIDIST", "SCOMIOTR",
    # Clases y Distribucion (6)
    "TIPO", "PERIODIV", "TIPONOT", "SHARE", "CLASEELE", "HEDGEDVL",
]

assert len(KEYS_ORDER) == 55, f"Se esperaban 55 claves, hay {len(KEYS_ORDER)}"
assert len(set(KEYS_ORDER)) == 55, "Hay claves duplicadas en KEYS_ORDER"


# ---------------------------------------------------------------------------
# Defaults canonicos (lo que va en el JSON cuando el folleto no lo provee)
# ---------------------------------------------------------------------------
DEFAULTS: dict[str, Any] = {
    # Base
    "NCFONDO": "No aplica",
    # Politica/Riesgo
    "PRIESGOF": None,
    "GARANT": 0,
    # Fechas garantia (null por defecto)
    "SVENGAR": None, "FVENGAR": None, "FINIGAR": None,
    "FCOMINI": None, "FCOMFIN": None, "PCOMER": None,
    # Comercializacion
    "DIVIBASE": "EURO",
    "VOLMAXP": "No existe.",
    "SAPMIN": "No existe.",
    # Comisiones (numericas)
    "COMIGEST": 0.0, "COMIRDO": 0.0, "COMIDEPO": 0.0,
    "COMIAPEX": 0.0, "COMIREEX": 0.0,
    # Comisiones (literales fijas)
    "COMIAPEN": "0", "COMIREEN": "0",
    "COMIDIST": "NO RELLENAR",
    # Comisiones derivadas S* (siempre string, nunca null)
    "SCOMIG": "0,00%", "SCOMID": "0,00%",
    "SCOMIA": "0,00%", "SCOMIR": "0,00%",
    "SDESCA": "0,00%", "SDESCR": "0,00%",
    "SCOMIRDO": "0,00% (sobre resultados positivos anuales del fondo)",
    "SCOMIOTR": "NO RELLENAR",
    # Clases / distribucion
    "TIPO": "Capitalización",
    "PERIODIV": "SIN PERIODICIDAD",
    "TIPONOT": 3,                # "Otros cambios" en extracciones periodicas
    "SHARE": "-",
    "CLASEELE": "-",
    "HEDGEDVL": 0,
}


# ---------------------------------------------------------------------------
# Codigos cerrados de TIPONOT (enumeracion oficial)
# ---------------------------------------------------------------------------
TIPONOT_CODES: dict[int, str] = {
    0: "Nuevo lanzamiento",
    1: "Cambio - Garantia",
    2: "Cambio - Politica de inversion",
    3: "Otros cambios",
}


def empty_record() -> "OrderedDict[str, Any]":
    """Devuelve un OrderedDict con las 55 claves en orden y valores
    inicializados con DEFAULTS (None donde no haya default)."""
    rec: "OrderedDict[str, Any]" = OrderedDict()
    for k in KEYS_ORDER:
        rec[k] = DEFAULTS.get(k, None)
    return rec
