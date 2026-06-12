"""Schemas de entrada y salida del endpoint del Asesor."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .profile import ClientProfile


class AdvisorRequest(BaseModel):
    """Cuerpo de POST /api/advisor/recommend."""

    profile: ClientProfile
    gestor_banco: Optional[str] = Field(
        None,
        description="Banco/Gestora del gestor; se prioriza en la recomendacion.",
    )


class FundMetricasUI(BaseModel):
    """Metricas mostradas en la cabecera de la card del fondo.

    Las comisiones provienen de la MISMA fuente que las metricas citadas en la
    justificacion (CSV VDOS), para que gestion <= total siempre cuadre.
    """

    comision_gestion: Optional[str] = None
    comision_total: Optional[str] = None
    plazo_recomendado: Optional[str] = None
    riesgo: Optional[int] = None
    riesgo_fuente: Optional[str] = Field(
        None,
        description="'CNMV' si viene del folleto (PRIESGOF) o 'vol' si se "
                    "deriva de la volatilidad (SRRI) por falta de PRIESGOF.",
    )
    garantizado: bool = False


class FundChipsUI(BaseModel):
    """Chips de categorizacion del fondo (etiquetas legibles)."""

    p00: Optional[str] = None  # categoria VDOS
    p05: Optional[str] = None  # region / divisa
    p06: Optional[str] = None  # sector / activo
    p20: Optional[str] = None  # subcategoria


class FundRecommendation(BaseModel):
    """Una fila de la seccion 'fondos recomendados'."""

    isin: str
    nombre: str
    gestora: Optional[str] = None
    peso_cartera_pct: float = 0
    justificacion: str = ""
    chips: FundChipsUI = Field(default_factory=FundChipsUI)
    metricas: FundMetricasUI = Field(default_factory=FundMetricasUI)
    provenance: Optional[str] = Field(
        None,
        description="Origen de la cita (folleto CNMV, ISIN, fecha).",
    )


class CarteraBloque(BaseModel):
    """Un bloque de la cartera modelo."""

    bloque: str
    peso_pct: float = 0
    isins: List[str] = Field(default_factory=list)


class CarteraModelo(BaseModel):
    descripcion: str = ""
    asignacion: List[CarteraBloque] = Field(default_factory=list)


class AdvisorResponse(BaseModel):
    """Respuesta normalizada del Asesor (sin codigos VDOS por defecto)."""

    recommendation_id: str
    resumen_ejecutivo: str = ""
    fondos_recomendados: List[FundRecommendation] = Field(default_factory=list)
    cartera_modelo: Optional[CarteraModelo] = None
    riesgos_y_advertencias: str = ""
    universo_size: int = 0
    raw: Optional[Dict[str, Any]] = Field(
        None,
        description="Respuesta cruda del LLM, solo en modo experto.",
    )
