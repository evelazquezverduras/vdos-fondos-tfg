"""risk_config.py -- Fuente UNICA de verdad de las bandas de riesgo por perfil.

Antes, los umbrales de volatilidad vivian duplicados en tres sitios con
valores distintos:
  - texto del SYSTEM_PROMPT del Asesor (rag/advisor.py)
  - _VOL_MAX_POR_PERFIL (web/.../services/adapters.py)  -> filtro duro
  - _VOL_TARGETS         (web/.../services/metricas_cuanti.py) -> idoneidad/radar

Eso provocaba incoherencias (el prompt decia "Moderado 5-15%" mientras el
codigo admitia hasta 20%). A partir de ahora TODOS leen estas constantes:
el prompt se genera a partir de ellas y los validadores las importan. Si hay
que cambiar un umbral, se cambia AQUI y en un solo sitio.

Convencion: volatilidad anualizada en fraccion (0.06 = 6%).
Cada perfil define (lo, ideal, hi):
  - hi    = maximo admisible (restriccion dura: por encima => descartar).
  - lo    = suelo del perfil (por debajo se considera infra-riesgo).
  - ideal = objetivo para normalizar el radar (score 100% en el ideal).
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

# perfil -> (lo, ideal, hi)  [fraccion de volatilidad anualizada]
VOL_BANDAS: Dict[str, Tuple[float, float, float]] = {
    "Conservador": (0.00, 0.02, 0.06),
    "Moderado":    (0.03, 0.10, 0.20),
    "Agresivo":    (0.10, 0.20, 0.50),
}


def normaliza_perfil(perfil: Optional[str]) -> str:
    """Normaliza a 'Conservador' | 'Moderado' | 'Agresivo' | ''."""
    p = (perfil or "").strip().lower()
    if p.startswith("conserv"):
        return "Conservador"
    if p.startswith("agres"):
        return "Agresivo"
    if p.startswith("moder"):
        return "Moderado"
    return ""


def banda(perfil: Optional[str]) -> Optional[Tuple[float, float, float]]:
    """Devuelve (lo, ideal, hi) del perfil normalizado, o None."""
    return VOL_BANDAS.get(normaliza_perfil(perfil))


def vol_max(perfil: Optional[str], default: float = 0.50) -> float:
    """Maximo admisible de volatilidad (hi) para el perfil."""
    b = banda(perfil)
    return b[2] if b else default


def vol_target(perfil: Optional[str]) -> Optional[Tuple[float, float, float]]:
    """Devuelve (ideal, lo, hi) -- orden esperado por metricas_cuanti."""
    b = banda(perfil)
    if not b:
        return None
    lo, ideal, hi = b
    return (ideal, lo, hi)


# Umbrales SRRI (CESR/ESMA) por volatilidad anualizada -> clase 1..7.
# Es la misma metodologia con la que se calcula el indicador de riesgo de los
# DFI/KID. La usamos como sustituto transparente cuando el PRIESGOF del folleto
# no esta disponible en los datos (campo vacio en el catalogo).
_SRRI_LIMITES = [0.005, 0.02, 0.05, 0.10, 0.15, 0.25]  # 6 cortes -> 7 clases


def srri_por_volatilidad(vol: Optional[float]) -> Optional[int]:
    """Devuelve la clase de riesgo 1..7 (estilo SRRI) para una volatilidad
    anualizada en fraccion (0.1257 = 12.57%). None si no hay dato."""
    if vol is None:
        return None
    try:
        v = float(vol)
    except (TypeError, ValueError):
        return None
    clase = 1
    for corte in _SRRI_LIMITES:
        if v >= corte:
            clase += 1
        else:
            break
    return clase


def _pct(x: float) -> str:
    """0.06 -> '6%'. Sin decimales si es entero, uno si no."""
    v = x * 100
    return f"{v:.0f}%" if abs(v - round(v)) < 1e-9 else f"{v:.1f}%"


def bloque_prompt_restricciones() -> str:
    """Genera el texto de RESTRICCIONES DURAS para el SYSTEM_PROMPT.

    Asi el prompt SIEMPRE refleja los mismos numeros que el filtro de codigo:
    no puede volver a desincronizarse.
    """
    lineas = []
    descripciones = {
        "Conservador": ("RF (corto y largo), monetarios, garantizados, "
                        "mixtos hasta 15% RV. NUNCA RV pura ni sectoriales."),
        "Moderado":    ("mixtos (15-75% RV), RV diversificada, RF largo, "
                        "garantizados de RV. Evita concentracion sectorial."),
        "Agresivo":    ("RV internacional, sectoriales tematicos, emergentes, "
                        "value concentrado, biotech, tech."),
    }
    for perfil, (lo, ideal, hi) in VOL_BANDAS.items():
        rango = (f"< {_pct(hi)}" if lo <= 0
                 else f"entre {_pct(lo)} y {_pct(hi)}")
        lineas.append(
            f"{perfil.upper()}:\n"
            f"  - Volatilidad media de la cartera: {rango} "
            f"(objetivo ~{_pct(ideal)}). Volatilidad por encima de {_pct(hi)} "
            f"= DESCARTAR el fondo, por buen Sharpe que tenga.\n"
            f"  - Categorias: {descripciones[perfil]}"
        )
    return "\n\n".join(lineas)
