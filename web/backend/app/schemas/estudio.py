"""Schemas Pydantic del Estudio comparativo Asesor VDOS vs ChatGPT."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Perfiles canonicos
# ---------------------------------------------------------------------------
class PerfilEstudio(BaseModel):
    """Uno de los 5 perfiles canonicos definidos en data/estudio/perfiles.json."""

    id: str
    etiqueta: str
    descripcion: str
    profile: Dict[str, Any]
    gestor_banco: Optional[str] = None


# ---------------------------------------------------------------------------
# Recomendacion normalizada (la misma forma sea quien sea el que la genera)
# ---------------------------------------------------------------------------
class FondoRec(BaseModel):
    """Un fondo dentro de una recomendacion."""

    isin: str
    nombre: str = ""
    peso_cartera_pct: Optional[float] = None
    justificacion: Optional[str] = ""


class RecomendacionRaw(BaseModel):
    """Recomendacion bruta: la salida del Asesor o el JSON de ChatGPT."""

    fuente: str  # "asesor_vdos" | "chatgpt"
    perfil_id: str
    modelo: Optional[str] = None
    timestamp: Optional[str] = None
    resumen_ejecutivo: str = ""
    fondos_recomendados: List[FondoRec] = Field(default_factory=list)
    cartera_modelo: Optional[Dict[str, Any]] = None
    riesgos_y_advertencias: Optional[str] = ""
    raw_text: Optional[str] = Field(
        None,
        description="Texto crudo que envio ChatGPT (por si no es JSON limpio)",
    )


# ---------------------------------------------------------------------------
# Rubrica automatica
# ---------------------------------------------------------------------------
class RubricaPorFondo(BaseModel):
    """Resultado de la rubrica para un fondo concreto."""

    isin: str
    nombre: str = ""
    existe_cnmv: bool = False  # ISIN presente en la base VDOS (fund_meta)
    isin_valido: bool = False  # ademas, nombre coherente (no alucinacion)
    nombre_coherente: Optional[bool] = None
    nombre_catalogo: str = ""
    es_nacional: bool = False
    riesgo_ok: Optional[bool] = None
    riesgo_observado: Optional[int] = None
    horizonte_ok: Optional[bool] = None
    horizonte_observado: Optional[str] = None
    esg_ok: Optional[bool] = None
    motivos_esg_fail: List[str] = Field(default_factory=list)


class RubricaGlobal(BaseModel):
    """Metricas agregadas a nivel cartera completa."""

    n_fondos: int = 0
    n_isins_validos: int = 0
    pct_isins_validos: float = 0.0
    n_nacionales: int = 0
    pct_nacionales: float = 0.0
    n_riesgo_ok: int = 0
    pct_riesgo_ok: float = 0.0
    n_horizonte_ok: int = 0
    pct_horizonte_ok: float = 0.0
    n_esg_ok: int = 0
    pct_esg_ok: float = 0.0
    hhi_gestoras: Optional[float] = Field(
        None,
        description="Herfindahl-Hirschman Index sobre gestoras (0=diversa, 1=monopolio)",
    )
    cobertura_sectorial_pct: Optional[float] = Field(
        None,
        description="% de sectores preferidos del cliente cubiertos por la recomendacion",
    )
    score_global: float = Field(
        0.0,
        description="Media ponderada de las metricas pct_*. 0 a 100.",
    )
    # Metricas cuantitativas reales del CSV VDOS (mas honestas que la rubrica
    # formal porque no dependen de campos que no extraemos).
    cuanti: Optional[Dict[str, Optional[float]]] = Field(
        None,
        description="Valores crudos: r1a, ra3, sharpe, com_total, volatilidad...",
    )
    cuanti_norm: Optional[Dict[str, Optional[float]]] = Field(
        None,
        description="Valores normalizados 0-100 para mostrar en barras del frontend.",
    )


class RecomendacionEvaluada(BaseModel):
    """Una recomendacion con su rubrica calculada."""

    raw: RecomendacionRaw
    por_fondo: List[RubricaPorFondo] = Field(default_factory=list)
    global_: RubricaGlobal = Field(default_factory=RubricaGlobal, alias="global")

    model_config = {"populate_by_name": True}


class ComparativaResponse(BaseModel):
    """Respuesta de /api/estudio/perfil/{id}/comparativa."""

    perfil: PerfilEstudio
    asesor_vdos: Optional[RecomendacionEvaluada] = None
    chatgpt: Optional[RecomendacionEvaluada] = None
    prompt_chatgpt: str = Field(
        ...,
        description="Prompt sugerido para pegar en chat.openai.com",
    )


# ---------------------------------------------------------------------------
# Entrada del paste de ChatGPT
# ---------------------------------------------------------------------------
class ChatGPTPasteRequest(BaseModel):
    """Body de POST /api/estudio/perfil/{id}/chatgpt-paste."""

    raw_text: str = Field(
        ..., description="JSON pegado directamente desde chat.openai.com"
    )
    modelo: Optional[str] = Field(
        None,
        description="Modelo de OpenAI usado, p.ej. 'gpt-4o', 'gpt-4o-mini', 'o3-mini'",
    )


# ---------------------------------------------------------------------------
# Panel avanzado (radar objetivo + kappa de Cohen)
# ---------------------------------------------------------------------------
class RadarEje(BaseModel):
    key: str
    label: str


class RadarObjetivo(BaseModel):
    asesor: Dict[str, Optional[float]]
    chatgpt: Dict[str, Optional[float]]
    crudo_asesor: Dict[str, Optional[float]] = Field(default_factory=dict)
    crudo_chatgpt: Dict[str, Optional[float]] = Field(default_factory=dict)
    ejes: List[RadarEje]


class KappaItem(BaseModel):
    label: str
    tipo: str
    kappa: Optional[float] = None
    ic_low: Optional[float] = None
    ic_high: Optional[float] = None
    p_o: Optional[float] = None
    n: int = 0
    alternativas: Optional[Dict[str, Optional[float]]] = None
    interpretacion: str = "n/d"
    nota: Optional[str] = None


class KappaPanel(BaseModel):
    n_fondos_asesor: int = 0
    n_fondos_chatgpt: int = 0
    n_fondos_comunes: int = 0
    n_fondos_union: int = 0
    items: List[KappaItem] = Field(default_factory=list)
    kappa_global: Optional[float] = None
    interpretacion_global: str = "n/d"


class PanelAvanzadoResponse(BaseModel):
    perfil_id: str
    perfil_etiqueta: str
    has_asesor: bool
    has_chatgpt: bool
    radar_objetivo: RadarObjetivo
    kappa: KappaPanel
