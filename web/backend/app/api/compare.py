"""Endpoints del Comparador de fondos."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..schemas.compare import (
    CompareRequest,
    CompareResponse,
    FundDetail,
    FundFilterOptions,
    FundSearchHit,
    SummaryRequest,
    SummaryResponse,
    TimeseriesResponse,
)
from ..services import funds_data, timeseries

router = APIRouter(prefix="/api", tags=["compare"])


# ---------------------------------------------------------------------------
# /api/funds/filters
# ---------------------------------------------------------------------------
@router.get("/funds/filters", response_model=FundFilterOptions)
def get_filters() -> FundFilterOptions:
    """Lista de tipos y gestoras disponibles para los selectores."""
    opts = funds_data.filter_options()
    return FundFilterOptions(**opts)


# ---------------------------------------------------------------------------
# /api/funds/search
# ---------------------------------------------------------------------------
@router.get("/funds/search", response_model=list[FundSearchHit])
def search_funds(
    q: str | None = Query(default=None, description="Texto libre: isin/nombre/gestora"),
    tipo: str | None = None,
    gestora: str | None = None,
    only_with_brochure: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[FundSearchHit]:
    """Autocomplete + filtros pre-busqueda. Devuelve hasta `limit` resultados."""
    hits = funds_data.search_funds(
        q=q,
        tipo=tipo,
        gestora=gestora,
        only_with_brochure=only_with_brochure,
        limit=limit,
    )
    return [FundSearchHit(**h) for h in hits]


# ---------------------------------------------------------------------------
# /api/funds/{isin}
# ---------------------------------------------------------------------------
@router.get("/funds/{isin}", response_model=FundDetail)
def get_fund(isin: str) -> FundDetail:
    """Ficha completa de un fondo. max_drawdown se omite (None)
    si se quiere con drawdown, usar /api/compare."""
    d = funds_data.build_fund_detail(isin)
    if not d:
        raise HTTPException(status_code=404, detail=f"ISIN {isin} no encontrado")
    return FundDetail(**d)


# ---------------------------------------------------------------------------
# /api/funds/{isin}/timeseries
# ---------------------------------------------------------------------------
@router.get("/funds/{isin}/timeseries", response_model=TimeseriesResponse)
def get_fund_timeseries(
    isin: str,
    desde: str | None = Query(default=None, description="YYYY-MM-DD"),
    hasta: str | None = Query(default=None, description="YYYY-MM-DD"),
) -> TimeseriesResponse:
    ts = funds_data.get_timeseries(isin, desde, hasta)
    if not ts["puntos"]:
        # No es error: el fondo existe pero no tiene VL en el rango.
        # 200 con lista vacia es semanticamente correcto.
        pass
    return TimeseriesResponse(**ts)


# ---------------------------------------------------------------------------
# POST /api/compare
# ---------------------------------------------------------------------------
@router.post("/compare", response_model=CompareResponse)
def compare(req: CompareRequest) -> CompareResponse:
    """Calcula todo lo necesario para pintar el comparador completo."""
    if req.isin_a == req.isin_b:
        raise HTTPException(
            status_code=400, detail="Selecciona dos ISINs distintos para comparar."
        )

    desde, hasta = funds_data._resolve_range(req.desde, req.hasta)

    raw_a = funds_data.get_raw_series(req.isin_a, desde, hasta)
    raw_b = funds_data.get_raw_series(req.isin_b, desde, hasta)
    if not raw_a:
        raise HTTPException(
            status_code=404,
            detail=f"Sin historico VL para {req.isin_a} en {desde}..{hasta}",
        )
    if not raw_b:
        raise HTTPException(
            status_code=404,
            detail=f"Sin historico VL para {req.isin_b} en {desde}..{hasta}",
        )

    calc = timeseries.compute_compare(raw_a, raw_b)

    detail_a = funds_data.build_fund_detail(req.isin_a, max_drawdown=calc["max_dd_a"])
    detail_b = funds_data.build_fund_detail(req.isin_b, max_drawdown=calc["max_dd_b"])
    if not detail_a:
        raise HTTPException(status_code=404, detail=f"Metadata no encontrada: {req.isin_a}")
    if not detail_b:
        raise HTTPException(status_code=404, detail=f"Metadata no encontrada: {req.isin_b}")

    return CompareResponse(
        isin_a=req.isin_a,
        isin_b=req.isin_b,
        desde=desde,
        hasta=hasta,
        n_a=len(raw_a),
        n_b=len(raw_b),
        n_alineados=calc["n_alineados"],
        fund_a=FundDetail(**detail_a),
        fund_b=FundDetail(**detail_b),
        series_a=calc["series_a"],
        series_b=calc["series_b"],
        derived=calc["derived"],
    )


# ---------------------------------------------------------------------------
# POST /api/compare/summary  (resumen IA)
# ---------------------------------------------------------------------------
_SUMMARY_SYSTEM = (
    "Eres un analista financiero senior. Resume las diferencias clave entre "
    "dos fondos de inversion para un gestor de banca privada en Espana. "
    "Estilo conciso, profesional, en espanol. Estructura: 2 a 3 parrafos. "
    "Menciona riesgo, rentabilidad, comisiones y horizonte. No inventes "
    "datos. Si una metrica no esta disponible, di 'no disponible'."
)


def _build_summary_user_prompt(fund_a: dict, fund_b: dict,
                               derived: dict, desde: str, hasta: str) -> str:
    def _fmt(v: Any, pct: bool = False) -> str:
        if v is None:
            return "n/d"
        if pct:
            return f"{float(v)*100:.2f}%"
        try:
            return f"{float(v):.4f}"
        except (TypeError, ValueError):
            return str(v)

    def _block(label: str, f: dict) -> str:
        r = f["returns"]
        risk = f["risk"]
        fees = f["fees"]
        brochure = f.get("brochure") or {}
        chips = " · ".join(filter(None, [
            brochure.get("p00_label"),
            brochure.get("p05_label"),
            brochure.get("p06_label"),
        ]))
        return (
            f"=== Fondo {label} ===\n"
            f"ISIN: {f['isin']}\n"
            f"Nombre: {f['nombre']}\n"
            f"Gestora: {f.get('gestora') or 'n/d'}\n"
            f"Tipo: {f.get('tipo') or 'n/d'}\n"
            f"Categoria CNMV: {chips or 'n/d'}\n"
            f"Snapshot: {f['structure'].get('fecha_snapshot') or 'n/d'}"
            f"{' (DESCATALOGADO)' if f.get('descatalogado') else ''}\n"
            f"Rentabilidad acumulada 1m / 3m / 6m / 1a / 3a / 5a: "
            f"{_fmt(r['r1m'], pct=True)} / {_fmt(r['r3m'], pct=True)} / "
            f"{_fmt(r['r6m'], pct=True)} / {_fmt(r['r1a'], pct=True)} / "
            f"{_fmt(r['r3a'], pct=True)} / {_fmt(r['r5a'], pct=True)}\n"
            f"Volatilidad: {_fmt(risk['volatilidad'], pct=True)} | "
            f"Sharpe: {_fmt(risk['sharpe'])} | "
            f"Max DD (rango): {_fmt(risk.get('max_drawdown'))}%\n"
            f"Comisiones: gestion {_fmt(fees['com_gestion'], pct=True)} | "
            f"depositario {_fmt(fees['com_depositario'], pct=True)} | "
            f"total {_fmt(fees['com_total'], pct=True)}\n"
            f"Patrimonio (miles EUR): "
            f"{_fmt(f['structure'].get('patrimonio_miles'))}\n"
        )

    return (
        f"Periodo analizado: {desde} a {hasta}.\n\n"
        f"{_block('A', fund_a)}\n"
        f"{_block('B', fund_b)}\n"
        f"=== Analisis derivado del historico VL ===\n"
        f"Correlacion de retornos diarios A-B: {_fmt(derived.get('correlacion'))}\n"
        f"Beta de A respecto a B: {_fmt(derived.get('beta_a_vs_b'))}\n"
        f"Observaciones alineadas: {derived.get('n_observations', 0)}\n\n"
        f"Escribe el resumen ejecutivo, 2 a 3 parrafos."
    )


@router.post("/compare/summary", response_model=SummaryResponse)
def compare_summary(req: SummaryRequest) -> SummaryResponse:
    """Resumen ejecutivo en lenguaje natural sobre las diferencias clave."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY no configurada. El resumen IA requiere LLM.",
        )

    desde, hasta = funds_data._resolve_range(req.desde, req.hasta)
    raw_a = funds_data.get_raw_series(req.isin_a, desde, hasta)
    raw_b = funds_data.get_raw_series(req.isin_b, desde, hasta)
    if not raw_a or not raw_b:
        raise HTTPException(
            status_code=404, detail="Falta historico VL para uno de los fondos."
        )

    calc = timeseries.compute_compare(raw_a, raw_b)
    detail_a = funds_data.build_fund_detail(req.isin_a, max_drawdown=calc["max_dd_a"])
    detail_b = funds_data.build_fund_detail(req.isin_b, max_drawdown=calc["max_dd_b"])
    if not detail_a or not detail_b:
        raise HTTPException(status_code=404, detail="Metadata no encontrada")

    user_prompt = _build_summary_user_prompt(
        detail_a, detail_b, calc["derived"], desde, hasta
    )

    try:
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = resp.choices[0].message.content or ""
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error de OpenAI: {e}")

    return SummaryResponse(text=text.strip())
