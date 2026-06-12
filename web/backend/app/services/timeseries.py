"""Calculos sobre series temporales de VL para el Comparador.

Funciones puras sobre numpy. NO dependen de pandas para no anadir dependencia.

Convencion: las series de entrada son listas alineadas de (fecha, vl), ya
ordenadas por fecha ascendente. La salida queda lista para serializar a JSON.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Alineacion de dos series por fecha
# ---------------------------------------------------------------------------
def align_two(
    series_a: list[tuple[str, float]],
    series_b: list[tuple[str, float]],
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Inner-join por fecha. Devuelve (fechas, vl_a, vl_b) alineadas."""
    map_a = dict(series_a)
    map_b = dict(series_b)
    common = sorted(set(map_a) & set(map_b))
    if not common:
        return [], np.array([]), np.array([])
    a = np.array([map_a[f] for f in common], dtype=float)
    b = np.array([map_b[f] for f in common], dtype=float)
    return common, a, b


# ---------------------------------------------------------------------------
# Transformaciones de una serie de VL
# ---------------------------------------------------------------------------
def base100(vl: np.ndarray) -> np.ndarray:
    """Normaliza la serie de VL a base 100 al inicio del rango."""
    if vl.size == 0:
        return vl
    v0 = vl[0]
    if v0 == 0 or not np.isfinite(v0):
        return np.full_like(vl, np.nan)
    return 100.0 * vl / v0


def ret_acumulada(vl: np.ndarray) -> np.ndarray:
    """Rentabilidad acumulada en % desde el inicio del rango."""
    if vl.size == 0:
        return vl
    v0 = vl[0]
    if v0 == 0 or not np.isfinite(v0):
        return np.full_like(vl, np.nan)
    return 100.0 * (vl / v0 - 1.0)


def drawdown(vl: np.ndarray) -> np.ndarray:
    """Drawdown desde maximo historico, en % (negativo o cero)."""
    if vl.size == 0:
        return vl
    running_max = np.maximum.accumulate(vl)
    # Evitar division por cero
    safe = np.where(running_max > 0, running_max, np.nan)
    return 100.0 * (vl - running_max) / safe


def max_drawdown(vl: np.ndarray) -> float | None:
    """Valor maximo absoluto del drawdown (positivo), o None si serie vacia."""
    if vl.size == 0:
        return None
    dd = drawdown(vl)
    dd_clean = dd[np.isfinite(dd)]
    if dd_clean.size == 0:
        return None
    return float(-dd_clean.min())  # positivo


# ---------------------------------------------------------------------------
# Retornos diarios y metricas derivadas
# ---------------------------------------------------------------------------
def daily_returns(vl: np.ndarray) -> np.ndarray:
    """log-returns diarios. Estable frente a saltos."""
    if vl.size < 2:
        return np.array([])
    # Saltos de fines de semana inflan el siguiente retorno; lo asumimos
    # consistente con la convencion de VDOS.
    safe = np.where(vl > 0, vl, np.nan)
    return np.log(safe[1:] / safe[:-1])


def rolling_vol(returns: np.ndarray, window: int) -> np.ndarray:
    """Volatilidad rolling anualizada (sqrt 252)."""
    if returns.size < window:
        return np.full(returns.size, np.nan)
    out = np.full(returns.size, np.nan)
    # Convolucion para la media
    cumsum = np.nancumsum(returns)
    cumsum_sq = np.nancumsum(returns ** 2)
    for i in range(window - 1, returns.size):
        if i == window - 1:
            s = cumsum[i]
            s2 = cumsum_sq[i]
        else:
            s = cumsum[i] - cumsum[i - window]
            s2 = cumsum_sq[i] - cumsum_sq[i - window]
        mean = s / window
        var = max(s2 / window - mean ** 2, 0.0)
        out[i] = math.sqrt(var) * math.sqrt(252)
    return out


def correlation(ret_a: np.ndarray, ret_b: np.ndarray) -> float | None:
    """Pearson sobre retornos diarios, ignorando NaNs."""
    mask = np.isfinite(ret_a) & np.isfinite(ret_b)
    if mask.sum() < 10:
        return None
    a = ret_a[mask]
    b = ret_b[mask]
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def beta_alpha(ret_a: np.ndarray, ret_b: np.ndarray) -> tuple[float | None, float | None]:
    """Regresion lineal r_a = alpha + beta * r_b. Devuelve (beta, alpha)
    en mismas unidades que los retornos diarios."""
    mask = np.isfinite(ret_a) & np.isfinite(ret_b)
    if mask.sum() < 10:
        return None, None
    a = ret_a[mask]
    b = ret_b[mask]
    var_b = b.var()
    if var_b == 0:
        return None, None
    cov = ((a - a.mean()) * (b - b.mean())).mean()
    beta = cov / var_b
    alpha = a.mean() - beta * b.mean()
    return float(beta), float(alpha)


def histogram(returns: np.ndarray, n_bins: int = 30) -> dict[str, Any]:
    """Histograma de retornos diarios listo para Plotly (UNA serie)."""
    clean = returns[np.isfinite(returns)]
    if clean.size == 0:
        return {"bin_edges": [], "counts": []}
    counts, edges = np.histogram(clean, bins=n_bins)
    return {
        "bin_edges": [float(e) for e in edges],
        "counts": [int(c) for c in counts],
    }


def histograms_dual(
    ret_a: np.ndarray,
    ret_b: np.ndarray,
    n_bins: int = 30,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Histogramas de A y B con MISMOS bin_edges para comparacion visual.

    Sin esto, cada serie tiene sus propios bins y el overlay queda
    desalineado: una barra de A en x=-0.012 y una de B en x=-0.011, casi
    superpuestas pero no comparables. Con bins comunes la grafica es
    legible.

    Para evitar que outliers raros distorsionen el rango (un dia con
    +20% solo, p.ej.) recortamos a percentiles [0.5, 99.5] de la union.
    """
    a = ret_a[np.isfinite(ret_a)]
    b = ret_b[np.isfinite(ret_b)]
    if a.size == 0 and b.size == 0:
        empty = {"bin_edges": [], "counts": []}
        return empty, empty
    union = np.concatenate([a, b])
    # Rango robusto: percentiles 0.5 a 99.5
    lo = float(np.percentile(union, 0.5))
    hi = float(np.percentile(union, 99.5))
    if lo == hi:
        lo, hi = lo - 0.01, hi + 0.01
    edges = np.linspace(lo, hi, n_bins + 1)
    counts_a, _ = np.histogram(a, bins=edges) if a.size else (np.zeros(n_bins, dtype=int), edges)
    counts_b, _ = np.histogram(b, bins=edges) if b.size else (np.zeros(n_bins, dtype=int), edges)
    edges_list = [float(e) for e in edges]
    return (
        {"bin_edges": edges_list, "counts": [int(c) for c in counts_a]},
        {"bin_edges": edges_list, "counts": [int(c) for c in counts_b]},
    )


# ---------------------------------------------------------------------------
# Empaquetado de las 4 series listas para Plotly
# ---------------------------------------------------------------------------
def _json_safe(arr: np.ndarray) -> list[float | None]:
    """Convierte np.ndarray a lista nullable para JSON (NaN -> None)."""
    return [None if not np.isfinite(x) else float(x) for x in arr]


def build_series(fechas: list[str], vl: np.ndarray) -> dict[str, Any]:
    """Calcula los 4 modos de chart para una serie."""
    return {
        "fechas": fechas,
        "base100": _json_safe(base100(vl)),
        "vl": _json_safe(vl),
        "ret_acum": _json_safe(ret_acumulada(vl)),
        "drawdown": _json_safe(drawdown(vl)),
    }


def build_rolling_vol(fechas: list[str], vl: np.ndarray) -> dict[str, Any]:
    """Tres ventanas (30, 60, 90 dias laborables) con su eje de fechas."""
    rets = daily_returns(vl)
    # Las fechas para rolling se desplazan 1 al frente (los retornos
    # corresponden al cierre del dia respecto al anterior).
    fechas_ret = fechas[1:] if len(fechas) > 1 else []
    return {
        "fechas": fechas_ret,
        "vol30": _json_safe(rolling_vol(rets, 30)),
        "vol60": _json_safe(rolling_vol(rets, 60)),
        "vol90": _json_safe(rolling_vol(rets, 90)),
    }


# ---------------------------------------------------------------------------
# API publica del comparador
# ---------------------------------------------------------------------------
def compute_compare(
    raw_a: list[tuple[str, float]],
    raw_b: list[tuple[str, float]],
) -> dict[str, Any]:
    """Coordina todo el calculo numerico del comparador.

    Recibe las dos series crudas (fecha, vl) del repositorio y devuelve un
    dict que satisface CompareSeries x2 + DerivedAnalysis + max_drawdown por
    fondo."""
    fechas, a, b = align_two(raw_a, raw_b)
    if not fechas:
        return {
            "fechas": [],
            "series_a": _empty_series(),
            "series_b": _empty_series(),
            "derived": _empty_derived(),
            "max_dd_a": None,
            "max_dd_b": None,
            "n_alineados": 0,
        }

    series_a = build_series(fechas, a)
    series_b = build_series(fechas, b)

    ret_a = daily_returns(a)
    ret_b = daily_returns(b)
    corr = correlation(ret_a, ret_b)
    beta, alpha = beta_alpha(ret_a, ret_b)

    derived = {
        "correlacion": corr,
        "beta_a_vs_b": beta,
        "alpha_a_vs_b": alpha,
        "n_observations": int(min(ret_a.size, ret_b.size)),
        "rolling_vol_a": build_rolling_vol(fechas, a),
        "rolling_vol_b": build_rolling_vol(fechas, b),
        # Histogramas con MISMOS bins (comparables visualmente)
        **dict(zip(
            ("histograma_a", "histograma_b"),
            histograms_dual(ret_a, ret_b),
        )),
    }
    return {
        "fechas": fechas,
        "series_a": series_a,
        "series_b": series_b,
        "derived": derived,
        "max_dd_a": max_drawdown(a),
        "max_dd_b": max_drawdown(b),
        "n_alineados": len(fechas),
    }


def _empty_series() -> dict[str, Any]:
    return {"fechas": [], "base100": [], "vl": [], "ret_acum": [], "drawdown": []}


def _empty_derived() -> dict[str, Any]:
    empty_vol = {"fechas": [], "vol30": [], "vol60": [], "vol90": []}
    empty_hist = {"bin_edges": [], "counts": []}
    return {
        "correlacion": None,
        "beta_a_vs_b": None,
        "alpha_a_vs_b": None,
        "n_observations": 0,
        "rolling_vol_a": empty_vol,
        "rolling_vol_b": empty_vol,
        "histograma_a": empty_hist,
        "histograma_b": empty_hist,
    }
