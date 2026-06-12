"""
p00_rules.py — Tabla determinista (P20 literal + P05 + P06) -> P00 (categoria comercial).

Esta tabla es HEURISTICA v1 y de demostracion. NOTA: los codigos internos
reales se han sustituido por codigos neutros autoexplicativos (RF_INTL,
RV_EURO, GARANT_RF, ...); la taxonomia oficial se omite por confidencialidad.
Las reglas estan ordenadas por prioridad: la primera que matchea gana.

Inputs:
  p20: literal P20 del folleto (mayusculas/minusculas, ej. "RENTA VARIABLE
       INTERNACIONAL", "GARANTIZADO DE RENDIMIENTO FIJO")
  p05_label: etiqueta legible P05 devuelta por el LLM (ej. "USA / USD")
  p06_label: etiqueta legible P06 devuelta por el LLM (ej. "TECNOLOGIA")

Output: codigo de categoria (str) o None si no aplica.

Categorias comerciales (codigos de ejemplo):
  MONETARIO  MONETARIO
  RF_CORTO  RF CORTO
  RF_LARGO  RF LARGO
  RF_MIXTA  RF MIXTA
  RV_MIXTA  RV MIXTA
  RV_NACIONAL  RV NACIONAL
  MONETARIO_INTL  MONETARIO INTERNACIONAL
  RF_INTL  RF INTERNACIONAL
  RF_MIXTA_INTL  RF MIXTA INTERNACIONAL
  RV_MIXTA_INTL  RV MIXTA INTERNACIONAL
  RV_EURO  RV EURO
  RV_INTL_OTROS  RVI RESTO
  GLOBAL  GLOBAL
  GARANT_RF  RF GARANTIZADO
  GARANT_RV  RV GARANTIZADO
  RV_INTL_USA  RVI EE.UU.
  RV_INTL_JAPON  RVI JAPON
  RV_INTL_EMERG  RVI EMERGENTES
  RV_INTL_EUROPA  RVI EUROPEA
  INMOBILIARIO  INMOBILIARIO
  INV_LIBRE  FONDO DE INVERSION LIBRE
  SIN_CLASIFICAR  SIN CLASIFICAR
"""

from __future__ import annotations
from typing import Optional


# Tokens que indican area geografica USA / Norteamerica.
_P05_USA = {
    "USA", "NORTEAMERICA", "CANADA", "ESTADOS UNIDOS", "EEUU",
}
# Tokens para Japon.
_P05_JAPON = {"JAPON"}
# Tokens para zonas emergentes.
_P05_EMERGENTES = {
    "EMERGENTES", "BRASIL", "MEXICO", "COLOMBIA", "CHILE", "PERU",
    "INDIA", "CHINA", "TAIWAN", "HONG KONG", "GRAN CHINA",
    "ASIA PACIFICO", "ASIA PACIFICO EX-JAPON", "AUSTRALASIA",
    "SUDESTE ASIATICO", "INDONESIA", "MALASIA", "TAILANDIA", "SINGAPUR",
    "COREA", "LATINOAMERICA", "EUROPA DEL ESTE", "RUSIA", "TURQUIA",
    "AFRICA", "ORIENTE PROXIMO", "EMERGENTES EMEA", "BRIC",
}
# Tokens para zona europea/Reino Unido/Suiza.
_P05_EUROPA = {
    "ZONA EURO", "EUROPA", "ESPAÑA", "ESPANA", "IBERIA", "PORTUGAL",
    "ALEMANIA", "FRANCIA", "ITALIA", "HOLANDA", "FINLANDIA", "BELGICA",
    "AUSTRIA", "REINO UNIDO", "SUIZA", "SUECIA", "NORUEGA", "DINAMARCA",
    "PAISES NORDICOS", "EUROPA EX-REINO UNIDO",
}


def _contains_any(s: str, tokens) -> bool:
    su = s.upper()
    return any(t in su for t in tokens)


def derive_p00(
    p20: Optional[str],
    p05_label: Optional[str] = None,
    p06_label: Optional[str] = None,
) -> Optional[str]:
    """Devuelve el codigo de categoria comercial (str) o None si no aplica.

    Reglas ordenadas; la primera que matchea gana."""
    if not p20:
        return None
    p20u = p20.upper().strip().rstrip(".")
    p05u = (p05_label or "").upper().strip()
    p06u = (p06_label or "").upper().strip()

    # ---- Garantizados (determinista por P20) ----
    if "GARANTIZADO" in p20u and ("RENDIMIENTO FIJO" in p20u or "REND.FIJO" in p20u or "REND FIJO" in p20u):
        return "GARANT_RF"
    if "GARANTIZADO" in p20u and ("RENDIMIENTO VARIABLE" in p20u or "REND.VAR" in p20u or "REND VAR" in p20u):
        return "GARANT_RV"

    # ---- Renta Variable Internacional con refinamiento por P05 ----
    if ("RENTA VARIABLE INTERNACIONAL" in p20u or "RV INTERNACIONAL" in p20u):
        if _contains_any(p05u, _P05_USA):
            return "RV_INTL_USA"
        if _contains_any(p05u, _P05_JAPON):
            return "RV_INTL_JAPON"
        if _contains_any(p05u, _P05_EMERGENTES):
            return "RV_INTL_EMERG"
        if _contains_any(p05u, _P05_EUROPA):
            return "RV_INTL_EUROPA"
        return "RV_INTL_OTROS"

    # ---- Renta Variable nacional / euro ----
    if "RENTA VARIABLE NACIONAL" in p20u or "RV NACIONAL" in p20u or "RV ESPAÑA" in p20u or "RV ESPANA" in p20u:
        return "RV_NACIONAL"
    if ("RENTA VARIABLE" in p20u and "EURO" in p20u) or "RV EURO" in p20u:
        return "RV_EURO"

    # ---- Renta Fija ----
    if "RENTA FIJA INTERNACIONAL" in p20u or "RF INTERNACIONAL" in p20u:
        return "RF_INTL"
    if ("RENTA FIJA" in p20u and "EURO" in p20u) or "RF EURO" in p20u:
        # Refinamiento por P06: corto plazo -> RF_CORTO, sino RF_LARGO.
        if "CORTO" in p20u or "CORTO" in p06u:
            return "RF_CORTO"
        return "RF_LARGO"

    # ---- Mixtos ----
    if "RV MIXTA INTERNACIONAL" in p20u:
        return "RV_MIXTA_INTL"
    if "RF MIXTA INTERNACIONAL" in p20u:
        return "RF_MIXTA_INTL"
    if "RV MIXTA" in p20u:
        return "RV_MIXTA"
    if "RF MIXTA" in p20u:
        return "RF_MIXTA"

    # ---- Monetarios ----
    if "MONETARIO INTERNACIONAL" in p20u:
        return "MONETARIO_INTL"
    if "MONETARIO" in p20u or p20u.startswith("FMM"):
        return "MONETARIO"

    # ---- Global ----
    if p20u == "GLOBAL" or " GLOBAL" in p20u:
        return "GLOBAL"

    # ---- Inmobiliario ----
    if "INMOBILIARIO" in p20u:
        return "INMOBILIARIO"

    # ---- IIC de inversion libre ----
    if "INVERSION LIBRE" in p20u:
        return "INV_LIBRE"

    # ---- Retorno absoluto / objetivo rentabilidad sin garantia ----
    # No tienen P00 directo. Se intenta clasificar por P06 si es muy claro.
    if "RETORNO ABSOLUTO" in p20u:
        return "SIN_CLASIFICAR"
    if "OBJETIVO" in p20u and "RENTABILIDAD" in p20u:
        # IIC con objetivo concreto de rentabilidad NO garantizado.
        # Por defecto SIN CLASIFICAR; regla a afinar.
        return "SIN_CLASIFICAR"

    # ---- IIC gestion pasiva / replica indice ----
    if "GESTION PASIVA" in p20u or "REPLICA" in p20u or "INDICE" in p20u:
        return "SIN_CLASIFICAR"  # afinar: indices europeos vs USA vs globales

    # Fallback
    return "SIN_CLASIFICAR"
