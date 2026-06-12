"""
validators.py — Validacion de un registro JSON.

Comprueba:
  - presencia de las 55 claves
  - tipos correctos
  - rangos legales: COMIGEST <= 2.25, COMIRDO <= 18, COMIDEPO <= 0.20,
    SDESCA/SDESCR/COMIAPEX/COMIREEX <= 5
  - flags 0/1: GARANT, HEDGEDVL
  - TIPONOT en {0,1,2,3}

Devuelve una lista de issues (vacia => valido).
"""

from __future__ import annotations
from typing import List, Dict, Any

from .schema import KEYS_ORDER, TIPONOT_CODES


LEGAL_LIMITS = {
    "COMIGEST": (0.0, 2.25),
    "COMIRDO":  (0.0, 18.0),
    "COMIDEPO": (0.0, 0.20),
    "COMIAPEX": (0.0, 5.0),
    "COMIREEX": (0.0, 5.0),
}


def validate(record: Dict[str, Any]) -> List[str]:
    issues: List[str] = []

    # 1. Cobertura de claves
    missing = [k for k in KEYS_ORDER if k not in record]
    if missing:
        issues.append(f"Faltan claves: {missing}")
    extra = [k for k in record if k not in KEYS_ORDER]
    if extra:
        issues.append(f"Claves no canonicas: {extra}")

    # 2. ISIN obligatorio y bien formado
    isin = record.get("ISIN", "")
    if not isin or len(isin) != 12 or not isin[:2].isalpha():
        issues.append(f"ISIN invalido: {isin!r}")

    # 3. Flags 0/1
    for k in ("GARANT", "HEDGEDVL"):
        v = record.get(k)
        if v not in (0, 1):
            issues.append(f"{k} debe ser 0 o 1, es {v!r}")

    # 4. TIPONOT
    if record.get("TIPONOT") not in TIPONOT_CODES:
        issues.append(f"TIPONOT fuera de catalogo: {record.get('TIPONOT')}")

    # 5. Rangos legales
    for field, (lo, hi) in LEGAL_LIMITS.items():
        v = record.get(field)
        if v is None:
            issues.append(f"{field} es null pero debe ser float")
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            issues.append(f"{field} no es numerico: {v!r}")
            continue
        if f < lo or f > hi:
            issues.append(f"{field}={f} fuera de rango legal [{lo}, {hi}]")

    # 6. Variables S* nunca null y siempre con %
    for k in ("SCOMIG", "SCOMID", "SCOMIA", "SCOMIR",
              "SDESCA", "SDESCR", "SCOMIRDO"):
        v = record.get(k)
        if not isinstance(v, str) or '%' not in v:
            issues.append(f"{k} debe ser string con '%', es {v!r}")

    # 7. Coherencia GARANT vs fechas garantia
    garant = record.get("GARANT", 0)
    fechas = ("SVENGAR", "FVENGAR", "FINIGAR",
              "FCOMINI", "FCOMFIN", "PCOMER")
    if garant == 0:
        for k in fechas:
            if record.get(k) is not None:
                issues.append(f"GARANT=0 pero {k} no es null: {record.get(k)!r}")
    elif garant == 1:
        # Las 6 fechas deben estar pobladas
        for k in fechas:
            if record.get(k) in (None, ""):
                issues.append(f"GARANT=1 pero {k} es null")
        # Coherencia FCOMFIN + 1 dia == FINIGAR
        fcomfin = record.get("FCOMFIN")
        finigar = record.get("FINIGAR")
        if fcomfin and finigar:
            from datetime import datetime, timedelta
            try:
                dt = datetime.strptime(fcomfin, "%d/%m/%Y")
                expected = (dt + timedelta(days=1)).strftime("%d/%m/%Y")
                if finigar != expected:
                    issues.append(
                        f"FINIGAR ({finigar}) no es FCOMFIN+1 ({expected})"
                    )
            except (ValueError, TypeError):
                issues.append(f"FCOMFIN no parseable como dd/mm/aaaa: {fcomfin!r}")
        # Coherencia PCOMER == 'FCOMINI - FCOMFIN'
        fcomini = record.get("FCOMINI")
        pcomer = record.get("PCOMER")
        if fcomini and fcomfin and pcomer:
            expected_pcomer = f"{fcomini} - {fcomfin}"
            if pcomer != expected_pcomer:
                issues.append(
                    f"PCOMER ({pcomer!r}) no coincide con '{expected_pcomer}'"
                )

    # 8. Defaults bloqueados
    if record.get("COMIDIST") != "NO RELLENAR":
        issues.append(f"COMIDIST debe ser 'NO RELLENAR' fijo")
    if record.get("COMIAPEN") != "0":
        issues.append("COMIAPEN debe ser literal '0' (string)")
    if record.get("COMIREEN") != "0":
        issues.append("COMIREEN debe ser literal '0' (string)")

    return issues
