"""
guarantee_fields.py — Extraccion de las 6 fechas de garantia para fondos
GARANTIZADOS o con OBJETIVO DE RENTABILIDAD.

Spec: docs/SPEC_GARANTIAS.md (literales y goldens).

API publica:
    extract_guarantee(text_compartment: str,
                      fees: dict,
                      freg_cnmv: str | None,
                      fcrec: str | None) -> dict
        -> {SVENGAR, FVENGAR, FINIGAR, FCOMINI, FCOMFIN, PCOMER}

Si el fondo no es garantizado, los 6 campos vienen a None desde el caller.
Aqui asumimos que el caller llama solo cuando GARANT == 1.
"""

from __future__ import annotations
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from .table_fees import normalize_date_ddmmyyyy


# ---------------------------------------------------------------------------
# Anclas regex sobre el texto del compartimento
# ---------------------------------------------------------------------------
RE_VENCIMIENTO = re.compile(
    r'garantiza\s+al\s+[Ff]ondo\s+a\s+vencimiento\s*'
    r'\((\d{1,2}[./]\d{1,2}[./]\d{2,4})\)',
    re.IGNORECASE,
)


def _add_one_day(ddmmyyyy: str) -> Optional[str]:
    """'04/05/2023' -> '05/05/2023'. Devuelve None si no parsea."""
    try:
        dt = datetime.strptime(ddmmyyyy, "%d/%m/%Y")
    except (ValueError, TypeError):
        return None
    return (dt + timedelta(days=1)).strftime("%d/%m/%Y")


def _vencimiento(text_compartment: str) -> Optional[str]:
    """FVENGAR: extrae fecha de vencimiento desde 'garantiza al fondo a
    vencimiento (DD/MM/AA)'. Devuelve dd/mm/aaaa o None."""
    m = RE_VENCIMIENTO.search(text_compartment or "")
    if not m:
        return None
    return normalize_date_ddmmyyyy(m.group(1))


def extract_guarantee(
    text_compartment: str,
    fees: Dict[str, Any],
    freg_cnmv: Optional[str],
    fcrec: Optional[str],
) -> Dict[str, Optional[str]]:
    """Construye el bloque de 6 fechas para fondos GARANT=1.

    Reglas (SPEC_GARANTIAS.md):
      - FVENGAR: del literal '...garantiza al fondo a vencimiento (FECHA)'.
      - SVENGAR: 'El ' + FVENGAR.
      - FCOMFIN: del primer tramo ('Hasta el FECHA, inclusive') de la
        tabla de comisiones fila Gestion. Llega ya normalizado en
        fees['_FCOMFIN_raw'].
      - FINIGAR: del segundo tramo ('Desde el FECHA, inclusive'). Llega
        en fees['_FINIGAR_raw']. Coherencia esperada: FCOMFIN + 1 dia.
      - FCOMINI: heuristica = freg_cnmv. Fallback = fcrec.
      - PCOMER: f'{FCOMINI} - {FCOMFIN}'.
    """
    fvengar = _vencimiento(text_compartment)
    svengar = f"El {fvengar}" if fvengar else None

    fcomfin = fees.get("_FCOMFIN_raw")
    finigar = fees.get("_FINIGAR_raw")
    # Coherencia: si solo tenemos uno, derivamos el otro
    if fcomfin and not finigar:
        finigar = _add_one_day(fcomfin)
    if finigar and not fcomfin:
        fcomfin = _subtract_one_day(finigar)

    # FCOMINI: registro CNMV; fallback constitucion
    fcomini = freg_cnmv or fcrec

    pcomer = (
        f"{fcomini} - {fcomfin}"
        if (fcomini and fcomfin) else None
    )

    return {
        "FVENGAR": fvengar,
        "SVENGAR": svengar,
        "FCOMFIN": fcomfin,
        "FINIGAR": finigar,
        "FCOMINI": fcomini,
        "PCOMER":  pcomer,
    }


def _subtract_one_day(ddmmyyyy: str) -> Optional[str]:
    try:
        dt = datetime.strptime(ddmmyyyy, "%d/%m/%Y")
    except (ValueError, TypeError):
        return None
    return (dt - timedelta(days=1)).strftime("%d/%m/%Y")
