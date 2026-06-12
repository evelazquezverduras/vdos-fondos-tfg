"""Endpoints del Estudio comparativo VDOS vs ChatGPT."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from ..deps import catalog_dep
from ..schemas.estudio import (
    ChatGPTPasteRequest,
    ComparativaResponse,
    KappaItem,
    KappaPanel,
    PanelAvanzadoResponse,
    PerfilEstudio,
    RadarObjetivo,
    RecomendacionEvaluada,
    RecomendacionRaw,
    RubricaGlobal,
    RubricaPorFondo,
)
from ..services import adapters, estudio, kappa, metricas_cuanti, rubrica
from ..services.catalog import Catalog


router = APIRouter(prefix="/api/estudio", tags=["estudio"])


# ---------------------------------------------------------------------------
# Perfiles
# ---------------------------------------------------------------------------
@router.get("/perfiles", response_model=List[PerfilEstudio])
def list_perfiles() -> List[PerfilEstudio]:
    return [PerfilEstudio(**p) for p in estudio.get_perfiles()]


@router.get("/perfil/{perfil_id}", response_model=PerfilEstudio)
def get_perfil(perfil_id: str) -> PerfilEstudio:
    p = estudio.get_perfil(perfil_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Perfil {perfil_id} no existe")
    return PerfilEstudio(**p)


# ---------------------------------------------------------------------------
# Ejecutar Asesor VDOS para un perfil (cachea en disco)
# ---------------------------------------------------------------------------
@router.post("/perfil/{perfil_id}/run-asesor", response_model=RecomendacionEvaluada)
def run_asesor(
    perfil_id: str, cat: Catalog = Depends(catalog_dep)
) -> RecomendacionEvaluada:
    p = estudio.get_perfil(perfil_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Perfil {perfil_id} no existe")

    profile = dict(p["profile"])
    if p.get("gestor_banco"):
        profile["gestora_propia"] = p["gestor_banco"]

    try:
        raw = adapters.call_advisor(profile, cat.records)
    except adapters.OpenAIKeyMissing as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Asesor IA: {e}")

    # Saneamos fondos antes de guardar (limpia el _record que mete advisor.py)
    saved = estudio.save_asesor_response(perfil_id, raw)
    return _build_evaluada(saved, p["profile"])


# ---------------------------------------------------------------------------
# Pegar/borrar respuesta de ChatGPT
# ---------------------------------------------------------------------------
@router.post("/perfil/{perfil_id}/chatgpt-paste", response_model=RecomendacionEvaluada)
def paste_chatgpt(
    perfil_id: str, body: ChatGPTPasteRequest
) -> RecomendacionEvaluada:
    p = estudio.get_perfil(perfil_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Perfil {perfil_id} no existe")
    if not body.raw_text or len(body.raw_text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Texto vacio o demasiado corto")
    saved = estudio.save_chatgpt_response(perfil_id, body.raw_text, body.modelo)
    return _build_evaluada(saved, p["profile"])


@router.delete("/perfil/{perfil_id}/chatgpt")
def delete_chatgpt(perfil_id: str) -> dict:
    ok = estudio.delete_chatgpt(perfil_id)
    return {"deleted": ok}


# ---------------------------------------------------------------------------
# Comparativa: trae todo lo necesario para pintar la pagina
# ---------------------------------------------------------------------------
@router.get("/perfil/{perfil_id}/comparativa", response_model=ComparativaResponse)
def get_comparativa(perfil_id: str) -> ComparativaResponse:
    p = estudio.get_perfil(perfil_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Perfil {perfil_id} no existe")

    asesor_raw = estudio.load_asesor(perfil_id)
    chatgpt_raw = estudio.load_chatgpt(perfil_id)

    return ComparativaResponse(
        perfil=PerfilEstudio(**p),
        asesor_vdos=_build_evaluada(asesor_raw, p["profile"]) if asesor_raw else None,
        chatgpt=_build_evaluada(chatgpt_raw, p["profile"]) if chatgpt_raw else None,
        prompt_chatgpt=estudio.build_prompt_for_chatgpt(p),
    )


# ---------------------------------------------------------------------------
# Panel avanzado: metricas objetivas (radar) + Kappa de Cohen
# ---------------------------------------------------------------------------
@router.get(
    "/perfil/{perfil_id}/panel-avanzado",
    response_model=PanelAvanzadoResponse,
)
def get_panel_avanzado(perfil_id: str) -> PanelAvanzadoResponse:
    """Devuelve el radar objetivo (7 ejes) + tabla de Kappa de Cohen para
    el perfil. Si falta alguno de los dos sistemas, el radar de ese sistema
    sale con None en todos los ejes y el Kappa sale vacio (n=0)."""
    p = estudio.get_perfil(perfil_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Perfil {perfil_id} no existe")

    asesor_raw = estudio.load_asesor(perfil_id)
    chatgpt_raw = estudio.load_chatgpt(perfil_id)

    fondos_a = asesor_raw["fondos_recomendados"] if asesor_raw else []
    fondos_b = chatgpt_raw["fondos_recomendados"] if chatgpt_raw else []

    panel = kappa.panel_metricas_avanzadas(fondos_a, fondos_b, p["profile"])

    return PanelAvanzadoResponse(
        perfil_id=perfil_id,
        perfil_etiqueta=p.get("etiqueta", ""),
        has_asesor=asesor_raw is not None,
        has_chatgpt=chatgpt_raw is not None,
        radar_objetivo=RadarObjetivo(**panel["radar_objetivo"]),
        kappa=KappaPanel(**panel["kappa"]),
    )


# ---------------------------------------------------------------------------
# Agregado: scores comparativos entre los 5 perfiles
# ---------------------------------------------------------------------------
@router.get("/agregado")
def get_agregado() -> Dict[str, Any]:
    """Devuelve por perfil y por sistema:
      - rubrica.global (validaciones formales)
      - metricas_cuanti (rentabilidad, sharpe, comisiones, vol, % VL)
        + normalizadas 0..100 para el resumen global.

    El resumen del frontend usa las metricas cuanti porque diferencian
    de verdad al Asesor de ChatGPT.
    """
    perfiles = estudio.get_perfiles()
    rows: List[Dict[str, Any]] = []
    for p in perfiles:
        row: Dict[str, Any] = {
            "perfil_id": p["id"],
            "etiqueta": p["etiqueta"],
            "asesor": None,
            "chatgpt": None,
        }

        perfil_riesgo = p["profile"].get("perfil_riesgo")

        a = estudio.load_asesor(p["id"])
        if a:
            ev = rubrica.evaluar_cartera(a["fondos_recomendados"], p["profile"])
            cuanti = metricas_cuanti.panel_cuanti(
                a["fondos_recomendados"], perfil_riesgo=perfil_riesgo)
            cuanti_norm = metricas_cuanti.normalize_para_radar(
                cuanti, perfil_riesgo=perfil_riesgo,
            )
            row["asesor"] = {
                **ev["global"],
                "cuanti": cuanti,
                "cuanti_norm": cuanti_norm,
            }

        c = estudio.load_chatgpt(p["id"])
        if c:
            ev = rubrica.evaluar_cartera(c["fondos_recomendados"], p["profile"])
            cuanti = metricas_cuanti.panel_cuanti(
                c["fondos_recomendados"], perfil_riesgo=perfil_riesgo)
            cuanti_norm = metricas_cuanti.normalize_para_radar(
                cuanti, perfil_riesgo=perfil_riesgo,
            )
            row["chatgpt"] = {
                **ev["global"],
                "cuanti": cuanti,
                "cuanti_norm": cuanti_norm,
            }

        rows.append(row)
    return {"rows": rows}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_evaluada(raw_record: Dict[str, Any],
                    profile: Dict[str, Any]) -> RecomendacionEvaluada:
    """Aplica la rubrica y devuelve el modelo Pydantic listo.

    Anade tambien las metricas cuantitativas (cuanti/cuanti_norm) al
    bloque global para que el frontend pueda mostrar Sharpe, r1a y
    comision total en la 'rubrica detallada' del perfil."""
    fondos = raw_record.get("fondos_recomendados") or []
    ev = rubrica.evaluar_cartera(fondos, profile)

    cuanti = metricas_cuanti.panel_cuanti(
        fondos, perfil_riesgo=profile.get("perfil_riesgo"))
    cuanti_norm = metricas_cuanti.normalize_para_radar(
        cuanti, perfil_riesgo=profile.get("perfil_riesgo"),
    )
    ev["global"]["cuanti"] = cuanti
    ev["global"]["cuanti_norm"] = cuanti_norm

    raw_model = RecomendacionRaw(
        fuente=raw_record.get("fuente", "?"),
        perfil_id=raw_record.get("perfil_id", "?"),
        modelo=raw_record.get("modelo"),
        timestamp=raw_record.get("timestamp"),
        resumen_ejecutivo=str(raw_record.get("resumen_ejecutivo") or ""),
        fondos_recomendados=fondos,
        cartera_modelo=raw_record.get("cartera_modelo"),
        riesgos_y_advertencias=str(raw_record.get("riesgos_y_advertencias") or ""),
        raw_text=raw_record.get("raw_text"),
    )

    return RecomendacionEvaluada(
        raw=raw_model,
        por_fondo=[RubricaPorFondo(**r) for r in ev["por_fondo"]],
        **{"global": RubricaGlobal(**ev["global"])},
    )
