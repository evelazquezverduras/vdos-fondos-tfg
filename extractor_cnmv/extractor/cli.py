"""
cli.py — Entry point para correr el extractor desde linea de comandos.

Uso:
    # Un solo folleto
    python -m extractor.cli ruta/al/folleto.pdf -o salida.json

    # Una carpeta completa (acumula todos los ISINs en un unico JSON)
    python -m extractor.cli ruta/a/pdfs/ -o pdfs_extracted.json --validate
"""

from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

from .assembler import extract, to_json
from .validators import validate


def _bootstrap_env() -> None:
    """Carga .env automaticamente desde rutas comunes del proyecto.

    Busca un .env en (orden de prioridad):
      1) directorio actual
      2) tfg/web/.env       (donde la web guarda OPENAI_API_KEY)
      3) tfg/.env
      4) tfg/extractor_cnmv/.env
    Claves API (OPENAI_API_KEY, GEMINI_API_KEY): si el .env las define,
    SOBREESCRIBEN al entorno del sistema. Esto evita problemas con claves
    antiguas persistidas en variables de Windows. El resto de claves solo
    se exportan si no estan ya en os.environ.
    """
    here = Path(__file__).resolve().parent  # tfg/extractor_cnmv/extractor
    tfg_dir = here.parents[1]  # tfg/
    candidates = [
        Path.cwd() / ".env",
        tfg_dir / "web" / ".env",
        tfg_dir / ".env",
        tfg_dir / "extractor_cnmv" / ".env",
    ]
    override_keys = {"OPENAI_API_KEY", "GEMINI_API_KEY"}
    for path in candidates:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if not k or not v:
                    continue
                if k in override_keys or k not in os.environ:
                    os.environ[k] = v
        except Exception:
            continue


_bootstrap_env()


def _extract_path(path: Path, dry_run_llm: bool) -> List[Dict[str, Any]]:
    """Procesa una ruta: si es PDF, devuelve sus registros; si es directorio,
    recorre *.pdf y agrega todos los registros con _source_pdf."""
    if path.is_dir():
        pdfs = sorted(path.glob("*.pdf"))
        all_records: List[Dict[str, Any]] = []
        for pdf in pdfs:
            recs = extract(str(pdf), dry_run_llm=dry_run_llm)
            for r in recs:
                r["_source_pdf"] = pdf.name
            all_records.extend(recs)
            print(f"  {pdf.name:40s} -> {len(recs)} ISIN(s)", file=sys.stderr)
        return all_records
    return extract(str(path), dry_run_llm=dry_run_llm)


def _run_phase3(records: List[Dict[str, Any]], provider: str, model: str,
                dry_run: bool) -> None:
    """Clasifica P05/P06 con el LLM elegido (Gemini u OpenAI) y deriva P00.

    Modifica `records` in-place."""
    from .llm import GeminiClassifier, OpenAIClassifier, classify_fund
    if provider == "openai":
        client = OpenAIClassifier(model=model, dry_run=dry_run)
        nombre = "OpenAI"
    else:
        client = GeminiClassifier(model=model, dry_run=dry_run)
        nombre = "Gemini"
    mode = "dry-run" if client.dry_run else f"real ({model})"
    print(f"\nFase 3 (LLM {nombre} {mode}): clasificando {len(records)} ISINs",
          file=sys.stderr)
    n_llm = 0
    n_skipped = 0
    for r in records:
        out = classify_fund(r, client=client)
        if out["P05"] is not None or out["P06"] is not None:
            n_llm += 1
        else:
            n_skipped += 1
        r["P05"] = out["P05"] if out["P05"] is not None else r.get("P05")
        r["P06"] = out["P06"] if out["P06"] is not None else r.get("P06")
        r["P00"] = out["P00"] if out["P00"] is not None else r.get("P00")
    stats = client.stats()
    print(f"  LLM: {n_llm} clasificados | {n_skipped} sin P05/P06 (dry o fallo) | "
          f"cache_size={stats['cache_size']}", file=sys.stderr)


def _print_validation(records: List[Dict[str, Any]]) -> None:
    ok = 0
    issues_total = 0
    for r in records:
        rr = {k: v for k, v in r.items() if k != "_source_pdf"}
        issues = validate(rr)
        if not issues:
            ok += 1
        else:
            issues_total += len(issues)
            src = r.get("_source_pdf", "")
            print(f"  [{r.get('ISIN')}] ({src}) {len(issues)} issues:",
                  file=sys.stderr)
            for it in issues[:6]:
                print(f"     * {it}", file=sys.stderr)
    print(f"\nValidate: {ok}/{len(records)} OK | "
          f"{issues_total} issues totales", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extractor CNMV: PDF (o carpeta) -> JSONs (1 por ISIN)."
    )
    parser.add_argument("path", help="Ruta a un PDF o a un directorio de PDFs")
    parser.add_argument("-o", "--output", help="Fichero de salida (default: stdout)")
    parser.add_argument("--no-llm", action="store_true",
                        help="Forzar dry-run del LLM en fase 1 (P05/P06)")
    parser.add_argument("--validate", action="store_true",
                        help="Reporta validacion por registro")
    parser.add_argument("--llm", choices=["gemini", "openai", "off"],
                        default="off",
                        help="Fase 3: clasificacion P05/P06 con LLM. "
                             "'gemini' usa GEMINI_API_KEY (modelo "
                             "gemini-2.5-flash por defecto); 'openai' usa "
                             "OPENAI_API_KEY (modelo gpt-4o-mini por defecto); "
                             "'off' (default) deja P05/P06 a null y solo "
                             "deriva P00 con la tabla determinista.")
    parser.add_argument("--llm-model", default=None,
                        help="Modelo concreto. Default: 'gemini-2.5-flash' "
                             "para --llm gemini, 'gpt-4o-mini' para "
                             "--llm openai.")
    parser.add_argument("--llm-dry-run", action="store_true",
                        help="Simula la fase 3 sin llamar a la API (muestra prompts)")
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"ERROR: no encuentro {args.path}", file=sys.stderr)
        return 1

    if path.is_dir():
        print(f"Procesando directorio: {path}", file=sys.stderr)
    records = _extract_path(path, dry_run_llm=args.no_llm)
    print(f"\nTotal ISINs: {len(records)}", file=sys.stderr)

    # ------ Fase 3: clasificacion P05/P06 (LLM) + derivacion P00 -----
    if args.llm in ("gemini", "openai") or args.llm_dry_run:
        provider = args.llm if args.llm in ("gemini", "openai") else "gemini"
        default_model = (
            "gpt-4o-mini" if provider == "openai" else "gemini-2.5-flash"
        )
        model = args.llm_model or default_model
        _run_phase3(records, provider=provider, model=model,
                    dry_run=args.llm_dry_run)
    else:
        # 'off' o default: aplicar solo derivacion P00 determinista.
        from .llm.p00_rules import derive_p00
        for r in records:
            if r.get("P00") is None:
                r["P00"] = derive_p00(r.get("P20"))

    if args.validate:
        _print_validation(records)

    out = to_json(records)
    if args.output:
        out_path = Path(args.output)
        out_path.write_text(out, encoding="utf-8")
        print(f"Escritos {len(records)} registros (literal) en {out_path}",
              file=sys.stderr)
        # Fase 2: traduccion a codigos canonicos VDOS via listapxx.
        codes_path = out_path.with_name(out_path.stem + "_codes.json")
        try:
            from .translator import translate_all, audit_unmatched
            translated = translate_all(records)
            codes_path.write_text(to_json(translated), encoding="utf-8")
            print(f"Escritos {len(translated)} registros (codigos) en {codes_path}",
                  file=sys.stderr)
            unmatched = audit_unmatched(records)
            for var, items in unmatched.items():
                if items:
                    print(f"  WARN: {len(items)} literales {var} sin match en catalogo:",
                          file=sys.stderr)
                    for it in items[:5]:
                        print(f"    - {it!r}", file=sys.stderr)
                    if len(items) > 5:
                        print(f"    ... +{len(items)-5} mas", file=sys.stderr)
        except FileNotFoundError as e:
            print(f"WARN: fase 2 (codigos) saltada: {e}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
