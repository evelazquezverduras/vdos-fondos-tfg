"""
assembler.py — Orquestador de extraccion: dado un PDF, produce N JSONs
(uno por ISIN) en formato canonico de 55 claves.
"""

from __future__ import annotations
import json
from typing import List, Dict, Any, Optional

from . import regex_fields as rf
from .helpers import build_nfondo
from .guarantee_fields import extract_guarantee
from .loader import load_text, load_native_tables
from .schema import empty_record, KEYS_ORDER
from .segmenter import segment, Segment
from .table_fees import parse_fees
from .validators import validate


def build_record(seg: Segment, *, dry_run_llm: bool = True,
                 native_tables: Optional[List[Dict]] = None,
                 num_cnmv: Optional[str] = None) -> Dict[str, Any]:
    """Construye un registro plano (55 claves) para un Segment."""
    rec = empty_record()

    # ------ Identidad -------------------------------------------------
    rec["ISIN"] = seg.isin
    rec["NFONDO"] = build_nfondo(seg.paraguas, seg.compartimento, seg.clase)
    rec["NCFONDO"] = "No aplica"

    # ------ Datos del fondo (text_fund) -------------------------------
    rec["FCREC"] = rf.fcrec(seg.text_fund)
    rec["AUDITOR"] = rf.auditor_label(seg.text_fund)

    # P02 (gestora) y P11 (depositario): LITERAL del folleto.
    # La traduccion a codigos canonicos VDOS (P02_GXXXX / P11_GXXXX) es
    # una fase posterior, fuera de este pipeline.
    rec["P02"] = rf.gestora_label(seg.text_fund)
    rec["P11"] = rf.depositario_label(seg.text_fund)

    # ------ Categoria del compartimento -------------------------------
    p01, p20 = rf.categoria(seg.text_compartment)
    rec["P01"] = p01
    rec["P20"] = p20
    # P00 / P05 / P06: en pausa hasta la fase de traduccion a codigos
    rec["P00"] = None
    rec["P05"] = None
    rec["P06"] = None

    # ------ Politica y derivados --------------------------------------
    # COMENT: texto integro de la politica de inversion (sin truncar).
    rec["COMENT"] = seg.politica_inversion
    rec["INFOREFB"] = rf.benchmark(seg.text_compartment)
    rec["DMINR"] = rf.dminr(seg.text_compartment)
    rec["GARANT"] = rf.garant_flag(seg.text_compartment)
    rec["HEDGEDVL"] = rf.hedged_flag(seg.text_compartment)
    rec["VOLMAXP"] = rf.volmaxp(seg.text_compartment)
    rec["PERIODVLP"] = rf.period_vlp(seg.text_compartment)

    # ------ Datos de la clase -----------------------------------------
    rec["DIVISA"] = rf.divisa(seg.text_class) or "euros"
    rec["TIPOPART"] = rf.tipopart(seg.text_class)

    apmin, uapmin = rf.aportacion_minima(seg.text_class)
    rec["APMIN"] = apmin
    rec["UAPMIN"] = uapmin
    rec["SAPMIN"] = rf.sapmin(seg.text_class)

    minim, uminim = rf.minimant(seg.text_class)
    rec["MINIMANT"] = minim
    rec["UMINMANT"] = uminim

    tipo, periodiv = rf.tipo_capdistr(seg.text_class)
    rec["TIPO"] = tipo
    rec["PERIODIV"] = periodiv or "SIN PERIODICIDAD"

    rec["SHARE"] = (seg.clase or "-").strip() or "-"
    rec["CLASEELE"] = rf.tipopart(seg.text_class) if seg.clase else "-"

    # ------ Comisiones (parser tabular) -------------------------------
    # native_tables filtra por bbox/seccion en una version posterior.
    # Por ahora pasamos el slice de la clase como fallback sintetico.
    fee_table_for_class = _filter_fee_table_for_class(native_tables, seg)
    fees = parse_fees(table_rows=fee_table_for_class,
                      text_class=seg.text_class)
    for k, v in fees.items():
        if k in KEYS_ORDER:
            rec[k] = v

    # ------ Garantia (6 fechas), solo si GARANT == 1 ------------------
    if rec["GARANT"] == 1:
        g = extract_guarantee(
            text_compartment=seg.text_compartment,
            fees=fees,
            freg_cnmv=rf.freg_cnmv(seg.text_fund),
            fcrec=rec.get("FCREC"),
        )
        for k in ("SVENGAR", "FVENGAR", "FINIGAR",
                  "FCOMINI", "FCOMFIN", "PCOMER"):
            rec[k] = g.get(k)

    return rec


def _filter_fee_table_for_class(
    native_tables: Optional[List[Dict]], seg: Segment
) -> Optional[List[List]]:
    """Si hay tablas nativas, intenta seleccionar la que pertenece al
    bloque de comisiones de ESTA clase. Heuristica simple: la primera
    tabla que contenga la cabecera 'Aplicada directamente al fondo'.
    En version siguiente se filtrara por pagina y proximidad al ISIN."""
    if not native_tables:
        return None
    for tbl in native_tables:
        rows = tbl.get("rows", [])
        joined = " ".join(
            (cell or "") for row in rows for cell in row
        ).lower()
        if "aplicada directamente al fondo" in joined:
            return rows
    return None


def extract(pdf_path: str, *, dry_run_llm: bool = True) -> List[Dict[str, Any]]:
    """Punto de entrada de mas alto nivel.

    Devuelve una lista de N registros JSON (uno por ISIN) listos para
    serializar y volcar a la base de datos relacional.
    """
    text = load_text(pdf_path)
    native_tables = load_native_tables(pdf_path)
    folleto = segment(text)
    out: List[Dict[str, Any]] = []
    for s in folleto.segments:
        rec = build_record(
            s,
            dry_run_llm=dry_run_llm,
            native_tables=native_tables,
            num_cnmv=folleto.num_cnmv,
        )
        out.append(rec)
    return out


def to_json(records: List[Dict[str, Any]], indent: int = 2) -> str:
    """Serializa preservando el orden canonico."""
    ordered = [{k: r.get(k) for k in KEYS_ORDER} for r in records]
    return json.dumps(ordered, ensure_ascii=False, indent=indent)
