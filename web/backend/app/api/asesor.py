"""Endpoint POST /api/advisor/recommend."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from ..deps import catalog_dep, expert_mode
from ..schemas.advisor import (
    AdvisorRequest,
    AdvisorResponse,
    CarteraBloque,
    CarteraModelo,
    FundChipsUI,
    FundMetricasUI,
    FundRecommendation,
)
from ..services import adapters, funds_data
from ..services.catalog import Catalog
from ..services.translate import code_to_label

from rag import risk_config  # type: ignore  # SRRI desde volatilidad

router = APIRouter(prefix="/api/advisor", tags=["asesor"])


@router.post("/recommend", response_model=AdvisorResponse)
def recommend(
    body: AdvisorRequest,
    cat: Catalog = Depends(catalog_dep),
    expert: bool = Depends(expert_mode),
) -> AdvisorResponse:
    """Genera la recomendacion del Asesor IA y la cachea en memoria."""
    profile = body.profile.to_dict()
    if body.gestor_banco:
        profile["gestora_propia"] = body.gestor_banco

    try:
        raw = adapters.call_advisor(profile, cat.records)
    except adapters.OpenAIKeyMissing as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Asesor IA: {e}")

    rid = adapters.store_recommendation(raw, profile)
    return _to_response(raw, rid, expert=expert)


def _to_response(raw: Dict[str, Any], rid: str, expert: bool) -> AdvisorResponse:
    """Normaliza la salida del LLM al esquema publico con etiquetas legibles."""
    fondos = [_fund_to_ui(f) for f in raw.get("fondos_recomendados") or []]

    cartera_dict = raw.get("cartera_modelo") or {}
    cartera = None
    if cartera_dict:
        cartera = CarteraModelo(
            descripcion=str(cartera_dict.get("descripcion") or ""),
            asignacion=[
                CarteraBloque(
                    bloque=str(b.get("bloque") or ""),
                    peso_pct=_to_float(b.get("peso_pct")),
                    isins=list(b.get("isins") or []),
                )
                for b in cartera_dict.get("asignacion") or []
            ],
        )

    return AdvisorResponse(
        recommendation_id=rid,
        resumen_ejecutivo=str(raw.get("resumen_ejecutivo") or ""),
        fondos_recomendados=fondos,
        cartera_modelo=cartera,
        riesgos_y_advertencias=str(raw.get("riesgos_y_advertencias") or ""),
        universo_size=int(raw.get("_universe_size") or 0),
        raw=raw if expert else None,
    )


def _fund_to_ui(f: Dict[str, Any]) -> FundRecommendation:
    r = f.get("_record") or {}
    isin = str(f.get("isin") or r.get("ISIN") or "")
    nombre = str(f.get("nombre") or r.get("NFONDO") or "")
    gestora = str(r.get("P02") or "") or None

    chips = FundChipsUI(
        p00=_label_or_none("P00", r.get("P00")),
        p05=_label_or_none("P05", r.get("P05")),
        p06=_label_or_none("P06", r.get("P06")),
        p20=_label_or_none("P20", r.get("P20")),
    )
    # Comisiones y riesgo desde la MISMA fuente que la justificacion (CSV VDOS),
    # para que la tarjeta sea coherente (gestion <= total) y el riesgo no quede
    # vacio cuando el folleto no trae PRIESGOF.
    meta = funds_data.get_meta(isin) if isin else None

    def _pct_meta(key: str) -> str | None:
        v = meta.get(key) if meta else None
        if isinstance(v, (int, float)):
            return f"{v * 100:.2f}%"
        return None

    com_gestion = _pct_meta("com_gestion") or (str(r.get("SCOMIG") or "") or None)
    com_total = _pct_meta("com_total")

    riesgo_val = r.get("PRIESGOF")
    if isinstance(riesgo_val, (int, float)):
        riesgo = int(riesgo_val)
        riesgo_fuente = "CNMV"
    else:
        vol = meta.get("volatilidad") if meta else None
        riesgo = risk_config.srri_por_volatilidad(vol)
        riesgo_fuente = "vol" if riesgo is not None else None

    metricas = FundMetricasUI(
        comision_gestion=com_gestion,
        comision_total=com_total,
        plazo_recomendado=str(r.get("DMINR") or "") or None,
        riesgo=riesgo,
        riesgo_fuente=riesgo_fuente,
        garantizado=bool(r.get("GARANT") == 1),
    )
    provenance = None
    fcrec = r.get("FCREC")
    if isin and fcrec:
        provenance = f"Folleto CNMV {isin} · {fcrec}"
    elif isin:
        provenance = f"Folleto CNMV {isin}"

    return FundRecommendation(
        isin=isin,
        nombre=nombre,
        gestora=gestora,
        peso_cartera_pct=_to_float(f.get("peso_cartera_pct")),
        justificacion=str(f.get("justificacion") or ""),
        chips=chips,
        metricas=metricas,
        provenance=provenance,
    )


def _label_or_none(var: str, value: Any) -> str | None:
    if value is None or value == "":
        return None
    return code_to_label(var, str(value)) or str(value)


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
