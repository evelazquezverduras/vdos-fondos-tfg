"""Schemas Pydantic del Comparador de fondos."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Resultado de busqueda en /api/funds/search
# ---------------------------------------------------------------------------
class FundSearchHit(BaseModel):
    """Una fila del autocomplete."""

    isin: str
    nombre: str
    gestora: str | None = None
    tipo: str | None = None
    has_brochure: bool = Field(
        False, description="True si el fondo esta en el JSON canon (folleto CNMV)"
    )


# ---------------------------------------------------------------------------
# Filtros disponibles para los selectores
# ---------------------------------------------------------------------------
class FundFilterOptions(BaseModel):
    tipos: list[str] = Field(default_factory=list)
    gestoras: list[str] = Field(default_factory=list)
    n_total: int = Field(0, description="Fondos en fund_meta (catalogo completo)")
    n_con_vl: int = Field(0, description="Fondos con historico de VL (comparables)")


# ---------------------------------------------------------------------------
# Ficha completa de un fondo
# ---------------------------------------------------------------------------
class FundFees(BaseModel):
    com_gestion: float | None = None
    com_depositario: float | None = None
    com_reembolso: float | None = None
    com_total: float | None = None
    retrocesion: float | None = None


class FundReturns(BaseModel):
    """Rentabilidades acumuladas y anualizadas del CSV de metadata."""

    r1d: float | None = None
    r1s: float | None = None
    r1m: float | None = None
    r3m: float | None = None
    r6m: float | None = None
    r1a: float | None = None
    r2a: float | None = None
    r3a: float | None = None
    r5a: float | None = None
    rinicio: float | None = None
    # Anualizadas
    ra: float | None = None
    ra1: float | None = None
    ra2: float | None = None
    ra3: float | None = None
    ra4: float | None = None
    ra5: float | None = None
    ra6: float | None = None
    # YTD
    ytd1: float | None = None
    ytd3: float | None = None
    ytd5: float | None = None


class FundRisk(BaseModel):
    volatilidad: float | None = None
    sharpe: float | None = None
    ratio_info: float | None = None
    tracking_error: float | None = None
    alfa: float | None = None
    beta: float | None = None
    r_cuadrado: float | None = None
    max_drawdown: float | None = Field(
        None,
        description="Calculado desde el historico VL del rango seleccionado",
    )


class FundQuartiles(BaseModel):
    qr1m: str | None = None
    qr3m: str | None = None
    qr1a: str | None = None
    qr3a: str | None = None
    qr5a: str | None = None
    prr1a: str | None = None
    prr3a: str | None = None
    prr5a: str | None = None


class FundStructure(BaseModel):
    """Tamano y antiguedad."""

    vl: float | None = None
    patrimonio_miles: float | None = None
    participaciones: float | None = None
    fecha_registro: str | None = None
    fecha_snapshot: str | None = None
    aportacion_minima: float | None = None
    divisa: str | None = None


class FundBrochure(BaseModel):
    """Subset del JSON canonico para los 447 fondos con folleto CNMV."""

    p00_label: str | None = None
    p05_label: str | None = None
    p06_label: str | None = None
    coment: str | None = None
    garant: int | None = None


class FundDetail(BaseModel):
    """Ficha completa devuelta por GET /api/funds/{isin}."""

    isin: str
    nombre: str
    gestora: str | None = None
    depositaria: str | None = None
    tipo: str | None = None
    cat_macro: str | None = None
    descatalogado: bool = Field(
        False,
        description="True si fecha_snapshot tiene >365 dias o no hay historico reciente",
    )
    fees: FundFees
    returns: FundReturns
    risk: FundRisk
    quartiles: FundQuartiles
    structure: FundStructure
    brochure: FundBrochure | None = Field(
        None, description="None si el fondo no esta en el JSON canon CNMV"
    )


# ---------------------------------------------------------------------------
# Series temporales (VL diario)
# ---------------------------------------------------------------------------
class TimeseriesPoint(BaseModel):
    fecha: str
    vl: float
    patrimonio: float | None = None


class TimeseriesResponse(BaseModel):
    isin: str
    desde: str
    hasta: str
    puntos: list[TimeseriesPoint]


# ---------------------------------------------------------------------------
# Comparativa completa (POST /api/compare)
# ---------------------------------------------------------------------------
ChartMode = Literal["base100", "vl", "ret_acum", "drawdown"]


class CompareRequest(BaseModel):
    isin_a: str
    isin_b: str
    desde: str | None = Field(
        None,
        description="YYYY-MM-DD, opcional. Por defecto: 5 anos atras",
    )
    hasta: str | None = Field(None, description="YYYY-MM-DD, opcional. Por defecto: hoy")


class CompareSeries(BaseModel):
    """4 modos de serie ya calculados, listos para Plotly."""

    fechas: list[str]
    base100: list[float | None]
    vl: list[float | None]
    ret_acum: list[float | None]
    drawdown: list[float | None]


class RollingVol(BaseModel):
    fechas: list[str]
    vol30: list[float | None]
    vol60: list[float | None]
    vol90: list[float | None]


class ReturnsHistogram(BaseModel):
    """Histograma de retornos diarios para una serie."""

    bin_edges: list[float]
    counts: list[int]


class DerivedAnalysis(BaseModel):
    correlacion: float | None = None
    beta_a_vs_b: float | None = None
    alpha_a_vs_b: float | None = None
    n_observations: int = 0
    rolling_vol_a: RollingVol
    rolling_vol_b: RollingVol
    histograma_a: ReturnsHistogram
    histograma_b: ReturnsHistogram


class CompareResponse(BaseModel):
    isin_a: str
    isin_b: str
    desde: str
    hasta: str
    n_a: int
    n_b: int
    n_alineados: int = Field(
        ..., description="Numero de fechas con VL disponible en AMBOS fondos"
    )
    fund_a: FundDetail
    fund_b: FundDetail
    series_a: CompareSeries
    series_b: CompareSeries
    derived: DerivedAnalysis


# ---------------------------------------------------------------------------
# Resumen IA
# ---------------------------------------------------------------------------
class SummaryRequest(BaseModel):
    isin_a: str
    isin_b: str
    desde: str | None = None
    hasta: str | None = None


class SummaryResponse(BaseModel):
    text: str
