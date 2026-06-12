"""
catalogs.py — Carga de catalogos label <-> code desde listapxx.xls.

listapxx.xls es la tabla maestra unificada: cada fila tiene
(idioma, var, value, label, labelc, priordad).

Expone helpers:
    catalog_lookup(var, label)   ->  code (e.g. 'P02_01')
    catalog_label(var, code)     ->  label legible
    has_catalog(var)             ->  bool
"""

from __future__ import annotations
import os
from functools import lru_cache
from typing import Dict, Optional

import pandas as pd

from .helpers import normalize_for_lookup

# ---------------------------------------------------------------------------
# Catalogos de EJEMPLO (version saneada). NOTA: los codigos internos
# reales se han sustituido por codigos neutros; la tabla maestra real
# (listapxx) se omite por confidencialidad.
# Se priorizan estos sobre listapxx para campos donde hay alias o sinonimos.
# ---------------------------------------------------------------------------
P00_CONSOLIDATED: Dict[str, str] = {
    "MONETARIO": "MONETARIO",
    "RF CORTO": "RF_CORTO",
    "RF LARGO": "RF_LARGO",
    "RF MIXTA": "RF_MIXTA",
    "RV MIXTA": "RV_MIXTA",
    "RV NACIONAL": "RV_NACIONAL",
    "MONETARIO INTERNACIONAL": "MONETARIO_INTL",
    "RF INTERNACIONAL": "RF_INTL",
    "RF MIXTA INTERNACIONAL": "RF_MIXTA_INTL",
    "RV MIXTA INTERNACIONAL": "RV_MIXTA_INTL",
    "RV EURO": "RV_EURO",
    "RVI EUROPEA": "RV_INTL_EUROPA",
    "RVI EE.UU.": "RV_INTL_USA",
    "RVI JAPON": "RV_INTL_JAPON",
    "RVI EMERGENTES": "RV_INTL_EMERG",
    "RVI RESTO": "RV_INTL_OTROS",
    "GLOBAL": "GLOBAL",
    "RF GARANTIZADO": "GARANT_RF",
    "RV GARANTIZADO": "GARANT_RV",
    "INMOBILIARIO": "INMOBILIARIO",
    "FONDO DE INVERSION LIBRE": "INV_LIBRE",
    "SIN CLASIFICAR": "SIN_CLASIFICAR",
}

P05_CONSOLIDATED: Dict[str, str] = {
    "ZONA EURO / EUR": "P05_01",
    "EUROPA / MULTIDIVISA": "P05_02",
    "USA / USD": "P05_03",
    "JAPON / JPY": "P05_04",
    "EMERGENTES / MULTIDIVISA": "P05_05",
    "GLOBAL / MULTIDIVISA": "P05_06",
    "AFRICA / MULTIDIVISA": "P05_07",
    "ASIA PACIFICO EX-JAPON / MULTIDIVISA": "P05_08",
    "AUSTRALASIA / MULTIDIVISA": "P05_09",
    "EUROPA DEL ESTE / MULTIDIVISA": "P05_10",
    "LATINOAMERICA / MULTIDIVISA": "P05_11",
    "ASIA PACIFICO / MULTIDIVISA": "P05_12",
    "GRAN CHINA / MULTIDIVISA": "P05_13",
    "ESPAÑA / EUR": "P05_14",
    "GLOBAL / EUR": "P05_15",
    "GLOBAL / USD": "P05_16",
}

P06_CONSOLIDATED: Dict[str, str] = {
    "CONSTRUCCION": "P06_01",
    "CONSUMO": "P06_02",
    "ECOLOGIA": "P06_03",
    "BIOTECNOLOGIA": "P06_04",
    "FINANCIERO": "P06_05",
    "MATERIAS PRIMAS": "P06_06",
    "TECNOLOGIA": "P06_07",
    "TELECOMUNICACIONES": "P06_08",
    "GLOBAL": "P06_09",
    "HIGH YIELD": "P06_10",
    "CONVERTIBLES": "P06_11",
    "SALUD": "P06_12",
    "ENERGIA": "P06_13",
    "UTILITIES": "P06_14",
    "GESTION ALTERNATIVA": "P06_15",
    "RENTA FIJA CORTO PLAZO": "P06_16",
    "DEUDA PUBLICA": "P06_17",
    "DEUDA PRIVADA": "P06_18",
    "INMOBILIARIOS": "P06_19",
    "ETICO": "P06_20",
    "RENTA FIJA": "P06_21",
    "RENTA VARIABLE": "P06_22",
    "MIXTO FLEXIBLE": "P06_23",
    "RETORNO ABSOLUTO": "P06_24",
}

# Override: estos diccionarios pisan a listapxx en caso de discrepancia
_OVERRIDES: Dict[str, Dict[str, str]] = {
    "P00": P00_CONSOLIDATED,
    "P05": P05_CONSOLIDATED,
    "P06": P06_CONSOLIDATED,
}

# ---------------------------------------------------------------------------
# Mapeo P20 -> P00
# Solo cubre las dos categorias de GARANTIZADOS (ejemplo).
# El resto de categorias sigue resolviendose via catalog_lookup('P00', label).
# ---------------------------------------------------------------------------
P20_TO_P00: Dict[str, str] = {
    "GARANTIZADO DE RENDIMIENTO FIJO":     "GARANT_RF",
    "GARANTIZADO DE RENDIMIENTO VARIABLE": "GARANT_RV",
}


def p20_to_p00(p20_label: Optional[str]) -> Optional[str]:
    """Devuelve el codigo P00 a partir de la etiqueta P20 cuando hay
    correspondencia determinista (caso garantizados). En cualquier otro
    caso devuelve None y deja al caller resolver via catalog_lookup."""
    if not p20_label:
        return None
    return P20_TO_P00.get(p20_label.strip().upper())


# ---------------------------------------------------------------------------
# Carga de listapxx.xls
#
# Estrategia de busqueda (en orden):
#   1) variable de entorno LISTAPXX_PATH si esta seteada
#   2) candidatos relativos al CWD y al modulo: criterios/, ../criterios/,
#      diccionario/, ../diccionario/, /mnt/project/listapxx.xls
# ---------------------------------------------------------------------------
def _autodetect_listapxx() -> str:
    env = os.environ.get("LISTAPXX_PATH")
    if env and os.path.exists(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        env or "",
        os.path.join(os.getcwd(), "criterios", "listapxx.xls"),
        os.path.join(os.getcwd(), "..", "criterios", "listapxx.xls"),
        os.path.join(os.getcwd(), "diccionario", "listapxx.xls"),
        os.path.join(os.getcwd(), "..", "diccionario", "listapxx.xls"),
        os.path.join(here, "..", "..", "criterios", "listapxx.xls"),
        os.path.join(here, "..", "..", "diccionario", "listapxx.xls"),
        "/mnt/project/listapxx.xls",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    # Fallback: devolver lo que pidio LISTAPXX_PATH (o vacio) para que el error
    # final mencione la ruta intentada.
    return env or candidates[-1]


DEFAULT_LISTAPXX = _autodetect_listapxx()


@lru_cache(maxsize=1)
def _load_listapxx(path: str = DEFAULT_LISTAPXX) -> pd.DataFrame:
    """Lee listapxx.xls una vez y cachea."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No encuentro listapxx.xls. Probado: {path}. "
            "Define LISTAPXX_PATH o coloca el .xls en criterios/."
        )
    df = pd.read_excel(path, sheet_name="listapxx")
    # Solo idioma ES por defecto
    df = df[df['idioma'] == 'ES'].copy()
    df['var'] = df['var'].astype(str).str.strip()
    df['value'] = df['value'].astype(str).str.strip()
    df['label'] = df['label'].astype(str).str.strip()
    return df


@lru_cache(maxsize=32)
def _build_label_to_code(var: str) -> Dict[str, str]:
    """Construye dict {normalize(label) -> code} para una variable."""
    df = _load_listapxx()
    sub = df[df['var'] == var]
    out: Dict[str, str] = {}
    for _, row in sub.iterrows():
        key = normalize_for_lookup(row['label'])
        if key and key not in out:
            out[key] = row['value']
    # Aplica overrides al final (pisan)
    if var in _OVERRIDES:
        for label, code in _OVERRIDES[var].items():
            out[normalize_for_lookup(label)] = code
    return out


@lru_cache(maxsize=32)
def _build_code_to_label(var: str) -> Dict[str, str]:
    df = _load_listapxx()
    sub = df[df['var'] == var]
    out: Dict[str, str] = {}
    for _, row in sub.iterrows():
        out[row['value']] = row['label']
    return out


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------
def has_catalog(var: str) -> bool:
    df = _load_listapxx()
    return var in set(df['var'].unique())


def catalog_lookup(var: str, label: str) -> Optional[str]:
    """label legible -> code interno. Devuelve None si no encuentra match."""
    if not label:
        return None
    table = _build_label_to_code(var)
    key = normalize_for_lookup(label)
    if key in table:
        return table[key]
    # Busqueda parcial: contains de la clave en alguna entrada
    for k, code in table.items():
        if key in k or k in key:
            return code
    return None


def catalog_label(var: str, code: str) -> Optional[str]:
    if not code:
        return None
    return _build_code_to_label(var).get(code)


def all_codes(var: str) -> Dict[str, str]:
    """Devuelve el dict completo {label_normalizado -> code} para esa variable.
    Util para el system prompt del LLM (lista cerrada de opciones)."""
    return dict(_build_label_to_code(var))


# Atajo: lista para system prompt del LLM (etiquetas legibles)
def llm_options(var: str) -> list[str]:
    """Lista de etiquetas legibles canonicas para inyectar en el prompt."""
    if var in _OVERRIDES:
        return list(_OVERRIDES[var].keys())
    df = _load_listapxx()
    sub = df[df['var'] == var]
    return sorted(set(sub['label'].astype(str).tolist()))
