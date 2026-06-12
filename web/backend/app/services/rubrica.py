"""Rubrica automatica del Estudio: aplica las 4 metricas a una recomendacion.

Metricas implementadas:
  1) ISIN valido en CNMV (existe en fund_meta del SQLite).
  2) Adecuacion de riesgo (PRIESGOF del fondo vs perfil del cliente).
  3) Respeto de exclusiones ESG (busqueda en COMENT).
  4) Coherencia de horizonte (DMINR del fondo vs horizonte del cliente).

Extras agregados a nivel cartera:
  - HHI sobre gestoras (concentracion).
  - Cobertura sectorial: % de sectores preferidos cubiertos.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

from . import funds_data
from .catalog import get_catalog


# Tokens genericos que no distinguen un fondo de otro.
_STOP_NOMBRE = {
    "FI", "FIM", "FIL", "SICAV", "CLASE", "SA", "SGIIC", "FONDO", "FONDOS",
    "DE", "DEL", "LA", "EL", "LOS", "LAS", "EUR", "USD", "INVERSION",
}


def _tokens_nombre(s: str) -> Set[str]:
    """Normaliza un nombre de fondo a un set de tokens significativos
    (sin acentos, sin ñ, sin clase ni sufijos genericos)."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9 ]", " ", s).upper()
    return {t for t in s.split() if len(t) >= 3 and t not in _STOP_NOMBRE}


def _nombre_coherente(nombre_modelo: str, nombre_catalogo: str) -> Optional[bool]:
    """¿El nombre que dio el modelo cuadra con el del catalogo para ese ISIN?

    Devuelve None si no se puede juzgar (algun nombre vacio). True/False segun
    cuantos tokens significativos comparten. Pilla casos como un ISIN real al
    que el modelo le pone un nombre de OTRO fondo (alucinacion de nombre)."""
    a, b = _tokens_nombre(nombre_modelo), _tokens_nombre(nombre_catalogo)
    if not a or not b:
        return None
    compartidos = a & b
    if len(compartidos) >= 2:
        return True
    # Un solo token en comun: solo es coherente si domina al nombre mas corto.
    return (len(compartidos) / min(len(a), len(b))) >= 0.5


# ---------------------------------------------------------------------------
# Mappings perfil cliente -> rangos aceptables
# ---------------------------------------------------------------------------

# Adecuacion de riesgo CNMV (PRIESGOF: 1-7, 7 = mas riesgo).
RIESGO_BY_PERFIL: Dict[str, Tuple[int, int]] = {
    "Conservador": (1, 3),
    "Moderado": (3, 5),
    "Agresivo": (5, 7),
}

# Horizontes del formulario -> "anos minimos aceptables"
# Si el fondo declara plazo recomendado mayor que el horizonte del cliente, fail.
HORIZONTE_MAX_ANOS: Dict[str, int] = {
    "< 1 año": 1,
    "1-3 años": 3,
    "3-5 años": 5,
    "5-10 años": 10,
    "> 10 años": 99,
    "Jubilación": 99,
}

# Palabras clave por exclusion ESG. Se buscan en COMENT (politica de inversion)
# Y opcionalmente en sectores tematicos. Si aparecen tal cual, flag.
ESG_KEYWORDS: Dict[str, List[str]] = {
    "Armas": ["armament", "defense", "defens", "weapon"],
    "Tabaco": ["tabaco", "tobacco"],
    "Combustibles fósiles": ["fosile", "petrole", "petrol", "carbon", "oil", "gas natural"],
    "Apuestas / juego": ["juego", "casino", "gambling", "apuestas"],
    "Pornografía": ["pornogra", "adult ent"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _isin_is_spanish(isin: str) -> bool:
    """ISIN nacional = empieza por 'ES' + 10 alfanumericos."""
    return bool(re.match(r"^ES[0-9A-Z]{10}$", isin or "", re.IGNORECASE))


def _extract_anos_from_dminr(dminr: str) -> Optional[int]:
    """Extrae el numero de anos del campo DMINR ('3 anos', '5 anos', '5+', ...).

    Devuelve el limite SUPERIOR del rango. None si no se puede parsear."""
    if not dminr:
        return None
    s = str(dminr).lower()
    # Buscar primer numero
    m = re.search(r"(\d+)", s)
    if not m:
        return None
    n = int(m.group(1))
    if "+" in s or "mas" in s or "más" in s:
        return n + 99  # no limite real
    return n


def _hhi(weights: List[float]) -> float:
    """Herfindahl-Hirschman Index sobre proporciones (suma a 1)."""
    if not weights:
        return 0.0
    s = sum(weights)
    if s <= 0:
        return 0.0
    norm = [w / s for w in weights]
    return sum(w * w for w in norm)


# ---------------------------------------------------------------------------
# Rubrica por fondo
# ---------------------------------------------------------------------------
def evaluar_fondo(
    isin: str,
    perfil_riesgo: str,
    horizonte: Optional[str],
    excluir: List[str],
    nombre_modelo: str = "",
) -> Dict[str, Any]:
    """Aplica las metricas a un fondo concreto.

    `nombre_modelo` es el nombre que dio el sistema (Asesor o ChatGPT). Se
    compara con el nombre real del catalogo para detectar alucinaciones de
    nombre (ISIN real emparejado con el nombre de otro fondo)."""
    es_nacional = _isin_is_spanish(isin)
    meta = funds_data.get_meta(isin)  # del SQLite fund_meta (base VDOS)
    existe_en_bd = meta is not None

    # Brochure del JSON canon (para PRIESGOF, DMINR, COMENT)
    cat = get_catalog()
    brochure = cat.by_isin.get(isin)

    # Coherencia ISIN <-> nombre. Solo se juzga si el ISIN existe en la base.
    nombre_catalogo = ""
    if meta:
        nombre_catalogo = meta.get("nombre") or ""
    elif brochure:
        nombre_catalogo = brochure.get("NFONDO") or ""
    nombre_coherente: Optional[bool] = None
    if existe_en_bd:
        nombre_coherente = _nombre_coherente(nombre_modelo, nombre_catalogo)
    # "No alucinacion" = el ISIN esta en la base VDOS Y el nombre cuadra.
    isin_valido = existe_en_bd and (nombre_coherente is not False)

    # Riesgo (necesita PRIESGOF del brochure)
    riesgo_observado: Optional[int] = None
    riesgo_ok: Optional[bool] = None
    if brochure and isinstance(brochure.get("PRIESGOF"), (int, float)):
        riesgo_observado = int(brochure["PRIESGOF"])
        rng = RIESGO_BY_PERFIL.get(perfil_riesgo)
        if rng:
            riesgo_ok = rng[0] <= riesgo_observado <= rng[1]

    # Horizonte (necesita DMINR)
    horizonte_observado: Optional[str] = None
    horizonte_ok: Optional[bool] = None
    if brochure and brochure.get("DMINR"):
        horizonte_observado = str(brochure["DMINR"])
        anos_fondo = _extract_anos_from_dminr(horizonte_observado)
        anos_cliente = HORIZONTE_MAX_ANOS.get(horizonte or "")
        if anos_fondo is not None and anos_cliente is not None:
            # Fondo a 5 anos para un cliente de < 1 ano -> fail.
            horizonte_ok = anos_fondo <= anos_cliente + 2  # tolerancia 2 anos

    # ESG
    esg_ok: Optional[bool] = None
    motivos_esg_fail: List[str] = []
    if excluir:
        coment = ""
        if brochure and brochure.get("COMENT"):
            coment = str(brochure["COMENT"]).lower()
        if coment:
            esg_ok = True
            for excl in excluir:
                kws = ESG_KEYWORDS.get(excl, [])
                for kw in kws:
                    if kw in coment:
                        esg_ok = False
                        motivos_esg_fail.append(f"{excl}: '{kw}' en politica")
                        break

    return {
        "isin": isin,
        "nombre": nombre_catalogo or nombre_modelo,
        "existe_cnmv": existe_en_bd,       # ISIN presente en la base VDOS
        "isin_valido": isin_valido,        # ademas, nombre coherente
        "nombre_coherente": nombre_coherente,
        "nombre_catalogo": nombre_catalogo,
        "es_nacional": es_nacional,
        "riesgo_ok": riesgo_ok,
        "riesgo_observado": riesgo_observado,
        "horizonte_ok": horizonte_ok,
        "horizonte_observado": horizonte_observado,
        "esg_ok": esg_ok,
        "motivos_esg_fail": motivos_esg_fail,
    }


# ---------------------------------------------------------------------------
# Rubrica global
# ---------------------------------------------------------------------------
def evaluar_cartera(
    fondos: List[Dict[str, Any]],
    perfil: Dict[str, Any],
) -> Dict[str, Any]:
    """Aplica la rubrica a la cartera completa.

    fondos = [{isin, nombre, peso_cartera_pct, justificacion}, ...]
    perfil = el dict 'profile' del perfil canonico.
    """
    perfil_riesgo = str(perfil.get("perfil_riesgo") or "Moderado")
    horizonte = perfil.get("horizonte")
    excluir = list(perfil.get("excluir") or [])
    sectores_pref = list(perfil.get("sectores") or [])

    por_fondo = [
        evaluar_fondo(f["isin"], perfil_riesgo, horizonte, excluir,
                      nombre_modelo=f.get("nombre") or "")
        for f in fondos
    ]

    n = len(por_fondo)
    # "No alucinacion" exige ISIN en base VDOS Y nombre coherente con ese ISIN.
    n_isins_validos = sum(1 for r in por_fondo if r["isin_valido"])
    n_nacionales = sum(1 for r in por_fondo if r["es_nacional"])
    # Solo cuentan los que SI se han podido evaluar:
    riesgos_evaluados = [r for r in por_fondo if r["riesgo_ok"] is not None]
    n_riesgo_ok = sum(1 for r in riesgos_evaluados if r["riesgo_ok"])

    horizontes_evaluados = [r for r in por_fondo if r["horizonte_ok"] is not None]
    n_horizonte_ok = sum(1 for r in horizontes_evaluados if r["horizonte_ok"])

    esg_evaluados = [r for r in por_fondo if r["esg_ok"] is not None]
    n_esg_ok = sum(1 for r in esg_evaluados if r["esg_ok"])

    def _pct(num: int, den: int) -> float:
        return round(100.0 * num / den, 1) if den > 0 else 0.0

    # HHI gestoras (necesita meta para conocer gestora real)
    gestoras: Dict[str, float] = {}
    for f, r in zip(fondos, por_fondo):
        if not r["existe_cnmv"]:
            continue
        meta = funds_data.get_meta(f["isin"])
        if not meta:
            continue
        g = meta.get("gestora") or "desconocida"
        peso = float(f.get("peso_cartera_pct") or (100.0 / max(n, 1)))
        gestoras[g] = gestoras.get(g, 0) + peso

    hhi = _hhi(list(gestoras.values())) if gestoras else None

    # Cobertura sectorial: % de sectores preferidos que estan en P06 de algun fondo
    cobertura_pct: Optional[float] = None
    if sectores_pref:
        cat = get_catalog()
        cubiertos: Set[str] = set()
        # Vamos a hacer match simple: si el nombre del sector aparece en
        # COMENT o como etiqueta P06 traducida.
        from .translate import code_to_label

        for f in fondos:
            r = cat.by_isin.get(f["isin"])
            if not r:
                continue
            etiquetas = []
            if r.get("P06"):
                etiquetas.append(code_to_label("P06", r["P06"]) or r["P06"])
            if r.get("P05"):
                etiquetas.append(code_to_label("P05", r["P05"]) or r["P05"])
            blob = " ".join(etiquetas).lower() + " " + (str(r.get("COMENT") or "").lower())
            for sec in sectores_pref:
                if sec.lower().split(" ")[0] in blob:
                    cubiertos.add(sec)
        cobertura_pct = round(100.0 * len(cubiertos) / len(sectores_pref), 1)

    # Score global ponderado (heuristico, 0 a 100). Solo cuenta las metricas
    # que han sido evaluadas; el resto se ignoran.
    weights_score = []
    weights_score.append(("isin_valido", _pct(n_isins_validos, n), 2.0))
    weights_score.append(("nacional", _pct(n_nacionales, n), 1.5))
    if riesgos_evaluados:
        weights_score.append(("riesgo", _pct(n_riesgo_ok, len(riesgos_evaluados)), 2.0))
    if horizontes_evaluados:
        weights_score.append(("horizonte", _pct(n_horizonte_ok, len(horizontes_evaluados)), 1.0))
    if esg_evaluados:
        weights_score.append(("esg", _pct(n_esg_ok, len(esg_evaluados)), 1.5))
    if cobertura_pct is not None:
        weights_score.append(("cobertura", cobertura_pct, 1.0))

    total_w = sum(w for _, _, w in weights_score) or 1.0
    score = sum(pct * w for _, pct, w in weights_score) / total_w
    score = round(score, 1)

    return {
        "por_fondo": por_fondo,
        "global": {
            "n_fondos": n,
            "n_isins_validos": n_isins_validos,
            "pct_isins_validos": _pct(n_isins_validos, n),
            "n_nacionales": n_nacionales,
            "pct_nacionales": _pct(n_nacionales, n),
            "n_riesgo_ok": n_riesgo_ok,
            "pct_riesgo_ok": _pct(n_riesgo_ok, len(riesgos_evaluados)) if riesgos_evaluados else 0.0,
            "n_horizonte_ok": n_horizonte_ok,
            "pct_horizonte_ok": _pct(n_horizonte_ok, len(horizontes_evaluados)) if horizontes_evaluados else 0.0,
            "n_esg_ok": n_esg_ok,
            "pct_esg_ok": _pct(n_esg_ok, len(esg_evaluados)) if esg_evaluados else 0.0,
            "hhi_gestoras": hhi,
            "cobertura_sectorial_pct": cobertura_pct,
            "score_global": score,
        },
    }
