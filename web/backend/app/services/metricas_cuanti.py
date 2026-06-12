"""metricas_cuanti.py -- Metricas cuantitativas de cartera basadas en datos VDOS reales.

A diferencia de rubrica.py (que valida reglas formales), aqui medimos
rendimiento historico, riesgo y eficiencia de coste de la cartera
recomendada. Estas son las metricas DIFERENCIADORAS frente a ChatGPT:
- ChatGPT no tiene acceso al historico VL diario.
- ChatGPT no tiene las metricas pre-computadas de VDOS (r1a, sharpe, vol).
- Si ChatGPT alucina un ISIN, no aparece en SQLite -> metrica N/A para el.

Todas las medias son PONDERADAS por peso_cartera_pct. Si un fondo no
tiene peso explicito, se asume reparto uniforme.

Funciones publicas:
  panel_cuanti(fondos) -> dict con las metricas crudas.
  normalize_para_radar(panel) -> dict con cada metrica mapeada a 0..100.

Convencion del radar:
  Mayor=mejor: rentabilidades, Sharpe, % VL completo.
  Menor=mejor: comisiones, volatilidad (se invierten al normalizar).
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from . import funds_data  # tambien inserta extractor_cnmv en sys.path
from rag import risk_config  # type: ignore  # fuente unica de bandas de riesgo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _weighted_avg(pairs: List[Tuple[float, float]]) -> Optional[float]:
    """Media ponderada de [(valor, peso), ...] ignorando None y peso<=0."""
    valid = [(v, w) for v, w in pairs
             if v is not None and w is not None and w > 0]
    if not valid:
        return None
    total_w = sum(w for _, w in valid)
    if total_w == 0:
        return None
    return sum(v * w for v, w in valid) / total_w


def _gather(fondos: List[Dict[str, Any]], key: str) -> List[Tuple[float, float]]:
    """Devuelve [(valor_metrica, peso_cartera), ...].

    Si el peso no esta declarado en el fondo, se asume reparto uniforme.
    Si el ISIN no existe en SQLite (fondo alucinado), no aporta valor.
    """
    n = max(len(fondos), 1)
    pares: List[Tuple[float, float]] = []
    for f in fondos:
        isin = (f.get("isin") or "").strip()
        if not isin:
            continue
        meta = funds_data.get_meta(isin)
        if not meta:
            continue  # alucinacion: no entra en la media
        v = meta.get(key)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        peso = f.get("peso_cartera_pct")
        if peso is None or peso <= 0:
            peso = 100.0 / n
        pares.append((v, float(peso)))
    return pares


# ---------------------------------------------------------------------------
# Metricas individuales
# ---------------------------------------------------------------------------
def rentabilidad_1a(fondos: List[Dict[str, Any]]) -> Optional[float]:
    """Rentabilidad media a 1 ano. Valor en fraccion (0.05 = 5%)."""
    return _weighted_avg(_gather(fondos, "r1a"))


def rentabilidad_3a_anualizada(fondos: List[Dict[str, Any]]) -> Optional[float]:
    """Rentabilidad anualizada a 3 anos."""
    return _weighted_avg(_gather(fondos, "ra3"))


def rentabilidad_5a_anualizada(fondos: List[Dict[str, Any]]) -> Optional[float]:
    """Rentabilidad anualizada a 5 anos."""
    return _weighted_avg(_gather(fondos, "ra5"))


def volatilidad_media(fondos: List[Dict[str, Any]]) -> Optional[float]:
    """Volatilidad anualizada media (en fraccion, 0.15 = 15%)."""
    return _weighted_avg(_gather(fondos, "volatilidad"))


def sharpe_medio(fondos: List[Dict[str, Any]]) -> Optional[float]:
    """Sharpe ratio medio."""
    return _weighted_avg(_gather(fondos, "sharpe"))


def comision_total_media(fondos: List[Dict[str, Any]]) -> Optional[float]:
    """Comision total media (gestion + deposito + otras) en fraccion."""
    return _weighted_avg(_gather(fondos, "com_total"))


def comision_gestion_media(fondos: List[Dict[str, Any]]) -> Optional[float]:
    return _weighted_avg(_gather(fondos, "com_gestion"))


def pct_fondos_con_vl(fondos: List[Dict[str, Any]]) -> Optional[float]:
    """% fondos cuyo ISIN tiene al menos 1 punto de VL historico.

    Mide cuantos de los ISINs recomendados son 'reales' con datos. Si
    ChatGPT alucina un ISIN, NO esta en vl_history -> baja esta metrica.
    """
    if not fondos:
        return None
    n = 0
    n_con_vl = 0
    for f in fondos:
        isin = (f.get("isin") or "").strip()
        if not isin:
            continue
        n += 1
        try:
            series = funds_data.get_raw_series(isin, "1900-01-01", "9999-12-31")
        except Exception:
            series = []
        if series:
            n_con_vl += 1
    if n == 0:
        return None
    return round(100.0 * n_con_vl / n, 1)


# ---------------------------------------------------------------------------
# Panel completo y normalizacion
# ---------------------------------------------------------------------------
def idoneidad_riesgo(fondos: List[Dict[str, Any]],
                     perfil_riesgo: Optional[str]) -> Optional[float]:
    """% del peso de cartera en fondos reales cuya volatilidad encaja con
    la banda de riesgo del perfil. Un ISIN sin datos (alucinado o sin
    serie) cuenta como NO idoneo: no se puede colocar capital de forma
    idonea en un fondo que no se puede verificar.

    Es la metrica que de verdad diferencia a un asesor regulado (MiFID):
    no premia rentar mas, premia colocar el capital en fondos apropiados
    para el perfil del cliente. Bandas (lo, hi) tomadas de _VOL_TARGETS.
    """
    if not fondos:
        return None
    rng = _VOL_TARGETS.get(perfil_riesgo or "")
    from . import funds_data
    n = max(len(fondos), 1)
    peso_total = 0.0
    peso_idoneo = 0.0
    for f in fondos:
        isin = (f.get("isin") or "").strip()
        peso = f.get("peso_cartera_pct")
        if peso is None or peso <= 0:
            peso = 100.0 / n
        peso_total += peso
        meta = funds_data.get_meta(isin) if isin else None
        vol = meta.get("volatilidad") if meta else None
        if vol is None or rng is None:
            continue
        _, lo, hi = rng
        try:
            if lo <= float(vol) <= hi:
                peso_idoneo += peso
        except (TypeError, ValueError):
            continue
    if peso_total <= 0:
        return None
    return round(100.0 * peso_idoneo / peso_total, 1)


def panel_cuanti(fondos: List[Dict[str, Any]],
                 perfil_riesgo: Optional[str] = None) -> Dict[str, Optional[float]]:
    """Diccionario con metricas crudas de la cartera. La idoneidad
    requiere el perfil de riesgo del cliente (banda de volatilidad)."""
    return {
        "rentabilidad_1a": rentabilidad_1a(fondos),
        "rentabilidad_3a_anual": rentabilidad_3a_anualizada(fondos),
        "rentabilidad_5a_anual": rentabilidad_5a_anualizada(fondos),
        "volatilidad": volatilidad_media(fondos),
        "sharpe": sharpe_medio(fondos),
        "comision_total": comision_total_media(fondos),
        "comision_gestion": comision_gestion_media(fondos),
        "idoneidad": idoneidad_riesgo(fondos, perfil_riesgo),
    }


# Rangos de normalizacion a 0..100 (decisiones documentadas).
# Si un valor cae fuera del rango se clipa al limite. Si es None, se
# mantiene como None (gap en el radar).
_RANGES: Dict[str, Tuple[float, float, bool]] = {
    # key:                (lo,   hi,   inverso)
    "rentabilidad_1a":      (-0.20,  0.30, False),
    "rentabilidad_3a_anual": (-0.10, 0.20, False),
    "rentabilidad_5a_anual": (-0.05, 0.15, False),
    "sharpe":               (-1.0,  3.0,  False),
    "comision_total":       ( 0.0,  0.03, True),  # menor = mejor
    "comision_gestion":     ( 0.0,  0.02, True),  # menor = mejor
    # volatilidad NO va aqui: se normaliza segun perfil (ver abajo)
}


# Volatilidad "ideal" por perfil de riesgo. La normalizacion se hace
# por distancia al ideal: score=100% si vol == ideal, baja linealmente
# hasta 0% en los limites del rango aceptable.
#
# Para CONSERVADOR vol baja es buena; para AGRESIVO vol baja es MALA
# (le hace perder rentabilidad por capitalizacion). Sin este ajuste,
# un sistema que recomendara monetarios para perfil agresivo "ganaria"
# en volatilidad artificialmente.
# Importado de risk_config (fuente unica). Formato (ideal, rango_low, rango_high).
# El rango_high coincide ahora con el maximo admisible del filtro duro, de modo
# que "idoneidad" y "descarte por volatilidad" usan exactamente la misma banda.
_VOL_TARGETS: Dict[str, Tuple[float, float, float]] = {
    perfil: risk_config.vol_target(perfil)
    for perfil in ("Conservador", "Moderado", "Agresivo")
}


def _score_volatilidad(vol: Optional[float], perfil_riesgo: Optional[str]) -> Optional[float]:
    """Score 0-100 de volatilidad segun perfil del cliente.

    100 = vol coincide con ideal del perfil.
    0   = vol esta fuera del rango aceptable del perfil.
    Penaliza simetricamente desviarse por arriba o por abajo.
    """
    if vol is None:
        return None
    try:
        v = float(vol)
    except (TypeError, ValueError):
        return None
    if not perfil_riesgo or perfil_riesgo not in _VOL_TARGETS:
        # Fallback al comportamiento clasico: menor = mejor en [0, 30%]
        v = max(0.0, min(0.30, v))
        return round(100.0 - 100.0 * v / 0.30, 1)
    ideal, lo, hi = _VOL_TARGETS[perfil_riesgo]
    if v <= lo or v >= hi:
        return 0.0
    if v <= ideal:
        # zona izquierda del ideal: penaliza si está demasiado bajo
        pct = (v - lo) / (ideal - lo) if ideal > lo else 1.0
    else:
        # zona derecha del ideal: penaliza si está demasiado alto
        pct = (hi - v) / (hi - ideal) if hi > ideal else 1.0
    return round(100.0 * max(0.0, min(1.0, pct)), 1)


def _map_range(v: Optional[float], lo: float, hi: float,
               inverso: bool) -> Optional[float]:
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    v = max(lo, min(hi, v))
    pct = 100.0 * (v - lo) / (hi - lo)
    return round(100.0 - pct if inverso else pct, 1)


def normalize_para_radar(
    panel: Dict[str, Optional[float]],
    perfil_riesgo: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """Mapea cada metrica a 0..100 segun los rangos definidos.

    perfil_riesgo: 'Conservador' | 'Moderado' | 'Agresivo'. Si None,
    la volatilidad se normaliza con la convencion clasica (menor=mejor).
    Si esta presente, la volatilidad se evalua por distancia al ideal
    del perfil (un agresivo NO quiere vol=0, quiere vol~20%).

    idoneidad ya viene en 0..100, se pasa tal cual (rama else).
    """
    out: Dict[str, Optional[float]] = {}
    for key, val in panel.items():
        if key == "volatilidad":
            out[key] = _score_volatilidad(val, perfil_riesgo)
        elif key in _RANGES:
            lo, hi, inv = _RANGES[key]
            out[key] = _map_range(val, lo, hi, inv)
        else:
            out[key] = val
    return out
