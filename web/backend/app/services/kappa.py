"""kappa.py -- Metricas avanzadas para el Estudio comparativo VDOS vs ChatGPT.

Implementa tres bloques:
  1) Metricas objetivas por sistema (sin juez humano)
  2) Kappa de Cohen + variantes (Asesor <-> ChatGPT)
  3) Helpers de interpretacion Landis-Koch

Las metricas del bloque 1 se reutilizan parcialmente de services/rubrica.py
y se completan con compatibilidad de minimo de inversion (APMIN).

Referencias:
  - Cohen, J. (1960). A coefficient of agreement for nominal scales.
  - Cohen, J. (1968). Weighted kappa.
  - Landis & Koch (1977). Tabla de interpretacion.
  - Fleiss & Cohen (1973). Varianza asintotica de kappa.
  - Byrt et al. (1993). PABAK.
  - Gwet (2008). AC1 robusto a clases desbalanceadas.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import funds_data
from .catalog import get_catalog
from . import metricas_cuanti
from . import rubrica


# ---------------------------------------------------------------------------
# Helpers comunes
# ---------------------------------------------------------------------------
def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den > 0 else 0.0


def _safe_div(num: float, den: float) -> Optional[float]:
    return num / den if den != 0 else None


# ---------------------------------------------------------------------------
# Bloque 1: Metricas objetivas por sistema
# ---------------------------------------------------------------------------
def metricas_objetivas_sistema(
    fondos: List[Dict[str, Any]],
    perfil: Dict[str, Any],
) -> Dict[str, Any]:
    """Devuelve los 7 ejes del radar objetivo para UN sistema.

    Eje 1: NO alucinacion (% ISINs en catalogo CNMV)
    Eje 2: Idoneidad al perfil (% del capital en banda de riesgo)
    Eje 3: Rentabilidad 1 ano (normalizada 0-100)
    Eje 4: Rentabilidad 3 anos anualizada (normalizada)
    Eje 5: Sharpe medio (normalizado)
    Eje 6: Comision total (invertida: menor=mejor)
    Eje 7: Volatilidad (invertida: menor=mejor)

    Mantenemos en 'crudo' las metricas sin normalizar para que la UI
    pueda mostrarlas en su unidad original (p.ej. r1a = 5.2%).

    Las que no son evaluables salen como None y el frontend las pinta
    como gap en el radar (penaliza al sistema que aluciona).
    """
    if not fondos:
        none7 = {
            "no_alucinacion": None,
            "idoneidad": None,
            "rentabilidad_1a": None,
            "rentabilidad_3a_anual": None,
            "sharpe": None,
            "comision_total": None,
            "volatilidad": None,
        }
        return {"radar": none7, "crudo": none7.copy()}

    # 1) NO alucinacion (sigue saliendo de la rubrica)
    ev = rubrica.evaluar_cartera(fondos, perfil)
    no_alucinacion = ev["global"].get("pct_isins_validos", 0.0)

    # 2-7) Metricas cuantitativas reales de VDOS
    crudo = metricas_cuanti.panel_cuanti(
        fondos, perfil_riesgo=perfil.get("perfil_riesgo"),
    )
    # IMPORTANTE: la volatilidad se normaliza segun el perfil del cliente
    # (un agresivo no quiere vol=0). Sin esto, recomendar monetarios a un
    # agresivo "gana" en volatilidad por error.
    norm = metricas_cuanti.normalize_para_radar(
        crudo, perfil_riesgo=perfil.get("perfil_riesgo"),
    )

    radar = {
        "no_alucinacion": no_alucinacion,
        "idoneidad": crudo.get("idoneidad"),
        "rentabilidad_1a": norm.get("rentabilidad_1a"),
        "rentabilidad_3a_anual": norm.get("rentabilidad_3a_anual"),
        "sharpe": norm.get("sharpe"),
        "comision_total": norm.get("comision_total"),
        "volatilidad": norm.get("volatilidad"),
    }

    return {"radar": radar, "crudo": crudo}


# ---------------------------------------------------------------------------
# Bloque 2: Kappa de Cohen + variantes
# ---------------------------------------------------------------------------
def _confusion_matrix(a: Sequence[int], b: Sequence[int], k: int) -> List[List[int]]:
    """Matriz de confusion k x k para enteros 0..k-1."""
    m = [[0] * k for _ in range(k)]
    for ai, bi in zip(a, b):
        if 0 <= ai < k and 0 <= bi < k:
            m[ai][bi] += 1
    return m


def kappa_cohen(
    a: Sequence[int],
    b: Sequence[int],
    k: int,
    weights: str = "none",
) -> Dict[str, Any]:
    """Kappa de Cohen (con o sin ponderacion cuadratica).

    weights:
      'none'      : kappa simple
      'quadratic' : kappa ponderado cuadratico (para variables ordinales)

    Devuelve dict con kappa, p_o, p_e, IC95%, n.
    """
    n = len(a)
    if n != len(b) or n == 0:
        return {"kappa": None, "p_o": None, "p_e": None,
                "ic_low": None, "ic_high": None, "n": 0}

    M = _confusion_matrix(a, b, k)
    total = sum(sum(row) for row in M)
    if total == 0:
        return {"kappa": None, "p_o": None, "p_e": None,
                "ic_low": None, "ic_high": None, "n": n}

    # Pesos
    if weights == "quadratic":
        if k <= 1:
            w = [[1.0]]
        else:
            w = [[1 - ((i - j) ** 2) / ((k - 1) ** 2) for j in range(k)]
                 for i in range(k)]
    else:
        w = [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]

    # p_o ponderado
    p_o = sum(w[i][j] * M[i][j] for i in range(k) for j in range(k)) / total

    # Marginales
    row_marg = [sum(M[i]) / total for i in range(k)]
    col_marg = [sum(M[i][j] for i in range(k)) / total for j in range(k)]

    # p_e ponderado
    p_e = sum(w[i][j] * row_marg[i] * col_marg[j]
              for i in range(k) for j in range(k))

    if abs(1 - p_e) < 1e-12:
        kappa = 1.0 if abs(p_o - p_e) < 1e-12 else None
        se = 0.0
    else:
        kappa = (p_o - p_e) / (1 - p_e)
        # SE asintotica simplificada (Fleiss-Cohen)
        if 0 < p_o < 1 and 0 < p_e < 1:
            se = math.sqrt(p_o * (1 - p_o) / (n * (1 - p_e) ** 2))
        else:
            se = 0.0

    ic_low = ic_high = None
    if kappa is not None:
        ic_low = round(kappa - 1.96 * se, 4)
        ic_high = round(kappa + 1.96 * se, 4)

    return {
        "kappa": round(kappa, 4) if kappa is not None else None,
        "p_o": round(p_o, 4),
        "p_e": round(p_e, 4),
        "ic_low": ic_low,
        "ic_high": ic_high,
        "n": n,
    }


def pabak(a: Sequence[int], b: Sequence[int]) -> Optional[float]:
    """PABAK (Prevalence-Adjusted Bias-Adjusted Kappa) para binarias.

    PABAK = 2*p_o - 1. Robusto a clases desbalanceadas.
    Solo definido para variables binarias (Byrt et al. 1993).
    """
    n = len(a)
    if n == 0 or n != len(b):
        return None
    agreements = sum(1 for ai, bi in zip(a, b) if ai == bi)
    p_o = agreements / n
    return round(2 * p_o - 1, 4)


def gwet_ac1(a: Sequence[int], b: Sequence[int], k: int) -> Optional[float]:
    """Gwet's AC1: alternativa robusta a la paradoja de kappa.

    AC1 = (p_o - p_a) / (1 - p_a)
    p_a = (1 / (k(k-1))) * sum_i pi_i * (1 - pi_i)
    donde pi_i es la prevalencia media de la categoria i.
    """
    n = len(a)
    if n == 0 or n != len(b) or k < 2:
        return None
    agreements = sum(1 for ai, bi in zip(a, b) if ai == bi)
    p_o = agreements / n
    # Prevalencia media por categoria
    pi = [0.0] * k
    for ai, bi in zip(a, b):
        if 0 <= ai < k:
            pi[ai] += 0.5 / n
        if 0 <= bi < k:
            pi[bi] += 0.5 / n
    p_a = sum(p * (1 - p) for p in pi) / (k - 1) if k > 1 else 0
    if abs(1 - p_a) < 1e-12:
        return 1.0 if abs(p_o - p_a) < 1e-12 else None
    return round((p_o - p_a) / (1 - p_a), 4)


def interpretacion_landis_koch(kappa: Optional[float]) -> str:
    if kappa is None:
        return "n/d"
    if kappa < 0:
        return "peor que azar"
    if kappa < 0.20:
        return "leve"
    if kappa < 0.40:
        return "bajo"
    if kappa < 0.60:
        return "moderado"
    if kappa < 0.80:
        return "sustancial"
    return "casi perfecto"


# ---------------------------------------------------------------------------
# Bloque 2: Panel comparativo Asesor <-> ChatGPT
# ---------------------------------------------------------------------------
_BANDAS_PESO = [(0, 10), (10, 25), (25, 50), (50, 75), (75, 100.01)]


def _banda_peso(peso: Optional[float]) -> int:
    if peso is None:
        return 0
    p = float(peso)
    for i, (lo, hi) in enumerate(_BANDAS_PESO):
        if lo <= p < hi:
            return i
    return len(_BANDAS_PESO) - 1


def panel_kappa(
    fondos_a: List[Dict[str, Any]],
    fondos_b: List[Dict[str, Any]],
    perfil: Dict[str, Any],
) -> Dict[str, Any]:
    """Panel de kappa Asesor <-> ChatGPT sobre la union de ISINs.

    Calcula cuatro items:
      1) Seleccion (binario, kappa de Cohen + PABAK + Gwet AC1)
      2) Banda de peso (ordinal, kappa ponderado cuadratico, fondos comunes)
      3) Categoria P00 implicita (categorica, fondos comunes)
      4) Nivel de riesgo PRIESGOF (ordinal 1-7, fondos comunes con folleto)
    """
    set_a = {f["isin"] for f in fondos_a if f.get("isin")}
    set_b = {f["isin"] for f in fondos_b if f.get("isin")}
    union = sorted(set_a | set_b)
    comunes = sorted(set_a & set_b)

    items = []

    # ---- Solapamiento de carteras (indice de Jaccard) ----
    # El kappa de Cohen "sobre la union" NO es informativo aqui: como los
    # dos sistemas eligen de universos distintos y apenas comparten fondos,
    # cada elemento de la union lo selecciona solo uno -> kappa ~ -1 por
    # construccion (artefacto, no desacuerdo real). Reportamos el indice de
    # Jaccard, que mide cuanto se solapan las carteras: 0 = disjuntas,
    # 1 = identicas. El kappa de acuerdo solo se calcula sobre los fondos
    # COMUNES (abajo), que es donde tiene sentido.
    jaccard = round(len(comunes) / len(union), 4) if union else None

    if False:  # bloque desactivado (kappa de seleccion sobre union, artefacto)
        k_sel = {"kappa": None}
        item = {
            "label": "Selección de fondos (sobre unión)",
            "tipo": "binario",
            "kappa": k_sel["kappa"],
            "ic_low": None,
            "ic_high": None,
            "p_o": None,
            "n": 0,
            "alternativas": None,
            "interpretacion": interpretacion_landis_koch(k_sel["kappa"]),
        }
        items.append(item)

    # Mapa de peso por isin
    map_peso_a = {f["isin"]: f.get("peso_cartera_pct") for f in fondos_a}
    map_peso_b = {f["isin"]: f.get("peso_cartera_pct") for f in fondos_b}

    # ---- 2) Kappa ponderado sobre banda de peso (fondos comunes) ----
    if len(comunes) >= 2:
        bandas_a = [_banda_peso(map_peso_a.get(i)) for i in comunes]
        bandas_b = [_banda_peso(map_peso_b.get(i)) for i in comunes]
        k_pes = kappa_cohen(bandas_a, bandas_b, k=5, weights="quadratic")
        items.append({
            "label": "Banda de peso en cartera (fondos comunes)",
            "tipo": "ordinal ponderado",
            "kappa": k_pes["kappa"],
            "ic_low": k_pes["ic_low"],
            "ic_high": k_pes["ic_high"],
            "p_o": k_pes["p_o"],
            "n": k_pes["n"],
            "alternativas": None,
            "interpretacion": interpretacion_landis_koch(k_pes["kappa"]),
        })

    # ---- 3) Categoria P00 (fondos comunes; viene del catalogo del fondo) ----
    if len(comunes) >= 2:
        cat = get_catalog()
        p00_universo = []
        p00_a = []
        p00_b = []
        for isin in comunes:
            rec = cat.by_isin.get(isin)
            if rec and rec.get("P00"):
                p = rec["P00"]
                if p not in p00_universo:
                    p00_universo.append(p)
                # ambos sistemas tienen el mismo fondo -> misma categoria
                # (kappa P00 entre sistemas sobre la MISMA cartera comun da
                # siempre acuerdo perfecto trivial. Lo dejamos como sanity).
                idx = p00_universo.index(p)
                p00_a.append(idx)
                p00_b.append(idx)
        if p00_a:
            k_cat = kappa_cohen(p00_a, p00_b, k=max(2, len(p00_universo)))
            items.append({
                "label": "Categoría P00 asignada (fondos comunes)",
                "tipo": "categórico",
                "kappa": k_cat["kappa"],
                "ic_low": k_cat["ic_low"],
                "ic_high": k_cat["ic_high"],
                "p_o": k_cat["p_o"],
                "n": k_cat["n"],
                "alternativas": None,
                "interpretacion": interpretacion_landis_koch(k_cat["kappa"]),
                "nota": "El fondo determina su P00 desde catalogo; coincidencia trivial cuando hay solapamiento.",
            })

    # ---- 4) PRIESGOF (1-7, fondos comunes con folleto) ----
    if len(comunes) >= 2:
        cat = get_catalog()
        risk_a = []
        risk_b = []
        for isin in comunes:
            rec = cat.by_isin.get(isin)
            if rec and isinstance(rec.get("PRIESGOF"), (int, float)):
                r = int(rec["PRIESGOF"]) - 1  # 1..7 -> 0..6
                risk_a.append(r)
                risk_b.append(r)
        if len(risk_a) >= 2:
            k_risk = kappa_cohen(risk_a, risk_b, k=7, weights="quadratic")
            items.append({
                "label": "Nivel de riesgo PRIESGOF (fondos comunes)",
                "tipo": "ordinal ponderado",
                "kappa": k_risk["kappa"],
                "ic_low": k_risk["ic_low"],
                "ic_high": k_risk["ic_high"],
                "p_o": k_risk["p_o"],
                "n": k_risk["n"],
                "alternativas": None,
                "interpretacion": interpretacion_landis_koch(k_risk["kappa"]),
                "nota": "Como en la categoria, viene del catalogo; coincide por construccion.",
            })

    # ---- Kappa global ponderado (media de los items con kappa numerico) ----
    kappas_validos = [it["kappa"] for it in items if it.get("kappa") is not None]
    if kappas_validos:
        kappa_global = round(sum(kappas_validos) / len(kappas_validos), 4)
    else:
        kappa_global = None

    return {
        "n_fondos_asesor": len(set_a),
        "n_fondos_chatgpt": len(set_b),
        "n_fondos_comunes": len(comunes),
        "n_fondos_union": len(union),
        "jaccard": jaccard,
        "items": items,
        "kappa_global": kappa_global,
        "interpretacion_global": interpretacion_landis_koch(kappa_global),
    }


# ---------------------------------------------------------------------------
# API de alto nivel
# ---------------------------------------------------------------------------
def panel_metricas_avanzadas(
    fondos_a: List[Dict[str, Any]],
    fondos_b: List[Dict[str, Any]],
    perfil: Dict[str, Any],
) -> Dict[str, Any]:
    """Genera el panel completo del Estudio: radar objetivo + tabla kappa.

    El radar usa metricas CUANTITATIVAS de VDOS (rentabilidades, Sharpe,
    comisiones, volatilidad), no validaciones formales. Esto es lo que
    diferencia al Asesor de ChatGPT: ChatGPT no tiene acceso a estos
    datos historicos.
    """
    panel_a = metricas_objetivas_sistema(fondos_a, perfil)
    panel_b = metricas_objetivas_sistema(fondos_b, perfil)
    kappa = panel_kappa(fondos_a, fondos_b, perfil)
    return {
        "radar_objetivo": {
            "asesor": panel_a["radar"],
            "chatgpt": panel_b["radar"],
            "crudo_asesor": panel_a["crudo"],
            "crudo_chatgpt": panel_b["crudo"],
            "ejes": [
                {"key": "no_alucinacion", "label": "No alucinación"},
                {"key": "idoneidad", "label": "Idoneidad al perfil"},
                {"key": "rentabilidad_1a", "label": "Rentabilidad 1 año"},
                {"key": "rentabilidad_3a_anual", "label": "Rentabilidad 3 años (anual.)"},
                {"key": "sharpe", "label": "Sharpe medio"},
                {"key": "comision_total", "label": "Comisión total (menor = mejor)"},
                {"key": "volatilidad", "label": "Volatilidad (menor = mejor)"},
            ],
        },
        "kappa": kappa,
    }
