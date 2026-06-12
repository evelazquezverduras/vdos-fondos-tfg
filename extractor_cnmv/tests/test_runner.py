"""
test_runner.py — Ejecuta el pipeline contra los 6 folletos prototipo y
compara con el Golden Set de ejemplo (cuando aplica).

Uso:
  python -m tests.test_runner
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Permitir import del paquete sin instalar
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extractor import extract, to_json, validate
from extractor.schema import KEYS_ORDER
from extractor.segmenter import segment
from extractor.loader import load_text


PROJECT_ROOT = Path(os.environ.get("PROTO_PDFS_DIR", "/mnt/project"))
PROTOTIPOS = [
    ("folleto_ejemplo_a.pdf",  "A", 1),   # simple sin clases
    ("folleto_ejemplo_b.pdf",  "A", 1),
    ("folleto_ejemplo_c.pdf",  "A", 1),
    ("folleto_ejemplo_d.pdf",  "B", 6),   # multiclase
    ("folleto_ejemplo_e.pdf",  "C", 5),   # compartimentos sin clases
    ("folleto_ejemplo_f.pdf",  "D", 15),  # compartimentos + clases
]

# Golden Set: fondo de EJEMPLO (Patron A, ES0000000002)
GOLDEN_EJEMPLO = {
    "ISIN": "ES0000000002",
    "NFONDO": "FONDO EJEMPLO RV INTERNACIONAL",
    "NCFONDO": "No aplica",
    "FCREC": "27/08/2025",
    "P02": "P02_01",
    "P11": "P11_01",
    "P01": "Fondo de Inversión",
    "P20": "RENTA VARIABLE INTERNACIONAL",
    "P00": "RV_INTL_EUROPA",
    "P05": "P05_01",
    "P06": "P06_01",
    "PRIESGOF": None,
    "DIVISA": "euros",
    "DIVIBASE": "EURO",
    "APMIN": 10.0,
    "UAPMIN": "euros",
    "MINIMANT": 10.0,
    "UMINMANT": "euros",
    "VOLMAXP": "No existe.",
    "COMIGEST": 0.3,
    "SCOMIG": "0,30%",
    "COMIRDO": 0.0,
    "SCOMIRDO": "0,00% (sobre resultados positivos anuales del fondo)",
    "COMIDEPO": 0.05,
    "SCOMID": "0,05%",
    "COMIAPEX": 0.0,
    "COMIAPEN": "0",
    "SCOMIA": "0,00%",
    "SDESCA": "0,00%",
    "COMIREEX": 0.0,
    "COMIREEN": "0",
    "SCOMIR": "0,00%",
    "SDESCR": "0,00%",
    "COMIDIST": "NO RELLENAR",
    "SCOMIOTR": "NO RELLENAR",
    "TIPO": "Capitalización",
    "PERIODIV": "SIN PERIODICIDAD",
    "TIPONOT": 3,
    "SHARE": "-",
    "CLASEELE": "-",
    "HEDGEDVL": 0,
    "GARANT": 0,
}


# ---------------------------------------------------------------------------
# Helpers de presentacion
# ---------------------------------------------------------------------------
def _short(v, max_len=80):
    s = repr(v)
    return s if len(s) <= max_len else s[:max_len - 3] + '...'


def diff_record(actual: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    """Compara dos registros campo a campo. Solo compara las claves
    presentes en `expected`. Devuelve lista de diferencias."""
    diffs: List[str] = []
    for k, exp in expected.items():
        act = actual.get(k)
        if act != exp:
            diffs.append(f"  - {k}: actual={_short(act)} | esperado={_short(exp)}")
    return diffs


def print_segmentation(name: str, expected_pattern: str, expected_n: int):
    """Lanza solo segmentacion y muestra patron + N ISINs detectados."""
    path = PROJECT_ROOT / name
    if not path.exists():
        print(f"  [SKIP] {name} no existe")
        return False, 0
    try:
        text = load_text(str(path))
        seg = segment(text)
    except Exception as e:
        print(f"  [ERROR] segmentacion {name}: {e}")
        return False, 0
    n = len(seg.segments)
    ok_pattern = seg.pattern == expected_pattern
    ok_count = n == expected_n
    flag = "OK" if (ok_pattern and ok_count) else "FAIL"
    print(f"  [{flag}] {name:30s} patron={seg.pattern} (esperado {expected_pattern})  "
          f"isins={n} (esperado {expected_n})  paraguas='{seg.paraguas[:50]}'")
    if seg.segments[:3]:
        for s in seg.segments[:3]:
            print(f"        - {s.isin} | comp='{(s.compartimento or '')[:30]}' | "
                  f"clase='{(s.clase or '')[:20]}'")
    return ok_pattern and ok_count, n


def run_segmentation_tests():
    print("=" * 78)
    print("STEP 1 — Segmentacion (regex sobre texto)")
    print("=" * 78)
    total_ok = 0
    for name, pat, n_expected in PROTOTIPOS:
        ok, _ = print_segmentation(name, pat, n_expected)
        if ok:
            total_ok += 1
    print(f"\n  Resultado: {total_ok}/{len(PROTOTIPOS)} prototipos segmentados OK")
    return total_ok


def run_full_pipeline_on(name: str):
    """Ejecuta extract() completo y muestra el primer JSON resultante."""
    path = PROJECT_ROOT / name
    if not path.exists():
        print(f"  [SKIP] {name} no existe")
        return None
    try:
        records = extract(str(path), dry_run_llm=True)
    except Exception as e:
        print(f"  [ERROR] pipeline en {name}: {e}")
        import traceback
        traceback.print_exc()
        return None
    print(f"\n  [{name}] -> {len(records)} JSON(s) generados, "
          f"{len(records[0]) if records else 0} claves cada uno")
    if records:
        # Muestra los primeros 12 campos del primer registro
        first = records[0]
        for k in KEYS_ORDER[:18]:
            print(f"     {k:12s} = {_short(first.get(k))}")
        # Cobertura
        n_filled = sum(1 for v in first.values() if v not in (None, ""))
        print(f"     ... ({n_filled}/{len(first)} claves rellenas)")
        # Validacion
        issues = validate(first)
        if not issues:
            print(f"     [validate] OK — sin issues")
        else:
            print(f"     [validate] {len(issues)} issues:")
            for it in issues[:6]:
                print(f"        * {it}")
    return records


def run_full_tests():
    print("\n" + "=" * 78)
    print("STEP 2 — Pipeline completo (segmentacion + regex_fields + table_fees + assembler)")
    print("=" * 78)
    print("(LLM en modo dry-run -> usa heuristica local para P05/P06)")
    for name, _, _ in PROTOTIPOS:
        run_full_pipeline_on(name)


def run_golden_diff():
    print("\n" + "=" * 78)
    print("STEP 3 — Comparacion con Golden Set (ejemplo ES0000000002)")
    print("=" * 78)
    print("NOTA: el PDF de ejemplo no esta en /mnt/project, asi que solo")
    print("podemos validar la ESTRUCTURA del Golden contra el schema:")
    issues = validate(GOLDEN_EJEMPLO)
    if not issues:
        print("  [OK] Golden Set valida contra el schema canonico de 55 claves")
    else:
        print(f"  [WARN] Golden tiene {len(issues)} issues contra el schema:")
        for i in issues[:10]:
            print(f"    * {i}")


def main():
    if not PROJECT_ROOT.exists():
        print(f"ERROR: no encuentro {PROJECT_ROOT}")
        return 1
    run_segmentation_tests()
    run_full_tests()
    run_golden_diff()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
