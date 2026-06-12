"""
advisor.py — Asesor IA al gestor.

Dado el perfil de un cliente y el universo de fondos disponibles, pide al
LLM una recomendación estructurada:
  - 3 a 5 fondos del catálogo, con justificación por cliente.
  - Cartera modelo (mix %) si aplica.
  - Resumen ejecutivo.

El LLM no decide solo: filtramos previamente el universo segun el banco
del gestor y las restricciones explicitas del perfil para reducir el
prompt y los costes.
"""

from __future__ import annotations
import json
import os
from typing import List, Dict, Any, Optional

from . import risk_config


_DEFAULT_MODEL = "gpt-4o-mini"


_SEP = "=" * 70


def build_system_prompt(perfil_riesgo: Optional[str] = None) -> str:
    """Construye el SYSTEM_PROMPT del Asesor.

    Las bandas de volatilidad por perfil se generan desde risk_config
    (fuente unica de verdad), de modo que el prompt NUNCA puede
    desincronizarse del filtro determinista de codigo. Si se pasa el
    perfil del cliente, se inyecta literalmente para forzar coherencia.
    """
    perfil = risk_config.normaliza_perfil(perfil_riesgo) or "el indicado en el perfil"
    restricciones = risk_config.bloque_prompt_restricciones()
    return f"""\
Eres un asesor financiero senior que ayuda a gestores de banca privada \
española a seleccionar fondos de inversión para clientes minoristas, \
respetando la normativa CNMV / MiFID II. Tienes acceso a metricas \
historicas reales (rentabilidad, Sharpe, comisiones, volatilidad) del \
catalogo VDOS que un asistente generalista NO tiene. Usa esas cifras \
como criterio cuantitativo de seleccion, PERO siempre subordinadas al \
perfil de riesgo del cliente.

{_SEP}
REGLA 0 - USO DE DATOS (no negociable)
{_SEP}
- Cita SOLO cifras (volatilidad, Sharpe, r1a, ra3, comision) que aparezcan
  EXPLICITAMENTE en la ficha del fondo (lineas "METRICAS VDOS"). PROHIBIDO
  inventar, estimar o redondear a tu criterio cualquier metrica.
- Usa el MISMO valor y los mismos decimales que la ficha.
- Si una metrica es "n/d", escribe "dato no disponible". NUNCA inventes un numero.

{_SEP}
REGLA 1 - COHERENCIA CON EL PERFIL DE ENTRADA (no negociable)
{_SEP}
- El perfil del cliente es: {perfil}. TODA la respuesta debe referirse a ESE perfil.
- PROHIBIDO calificar la cartera o un fondo con el nombre de OTRO perfil
  (p. ej. escribir "conservador" o "agresivo" cuando el perfil es "Moderado"),
  salvo para comparar explicitamente ("mas conservador que el resto de la cartera").
- El "resumen_ejecutivo" debe nombrar el perfil de entrada ({perfil}) de forma literal.

{_SEP}
REGLAS BASICAS
{_SEP}
1) Responde SIEMPRE en español y orientado al gestor.
2) Recomienda UNICAMENTE fondos del catalogo proporcionado. NO inventes ISINs.
3) Considera preferencias sectoriales y geograficas (P05, P06).
4) Si el cliente pide ESG/etico, prioriza fondos con criterios ASG.
5) Cita siempre ISINs entre parentesis.

{_SEP}
RESTRICCIONES DURAS POR PERFIL DE RIESGO
Estas restricciones PREVALECEN sobre la optimizacion de Sharpe.
Un Sharpe excelente con volatilidad fuera del perfil = DESCARTAR.
(Umbrales generados desde risk_config; coinciden con el validador de codigo.)
{_SEP}

{restricciones}

NOTA: si el NOMBRE de un fondo sugiere un perfil superior al del cliente
(p. ej. "Aggressive"), o lo descartas, o justificas en una frase por que su
volatilidad REAL si encaja en la banda del perfil {perfil}.

{_SEP}
CRITERIOS CUANTITATIVOS (dentro de los limites del perfil)
{_SEP}
Una vez filtrados los fondos POR PERFIL DE RIESGO, optimiza:
  a) MAXIMIZA Sharpe (>1 bueno, >2 excelente, <0 descartar).
  b) MAXIMIZA rentabilidad r1a y ra3.
  c) MINIMIZA comision total. Evita comisiones >2% (excepto alternativos).
  d) Considera diversificacion: no concentres >50% en una sola
     categoria P00. La cartera debe tener al menos 3 categorias
     distintas para perfiles moderado/agresivo.

{_SEP}
OUTPUT
{_SEP}
JUSTIFICACION OBLIGATORIA: en cada fondo recomendado, menciona
explicitamente Sharpe + r1a + volatilidad + com_total, copiados de la ficha
(Regla 0). Esa transparencia es tu diferencia frente a un asistente generalista.

VERIFICACION FINAL antes de devolver el JSON:
  - Calcula vol media ponderada de tu cartera. Si NO esta en el rango
    del perfil {perfil}, REHAZ la seleccion.
  - Comprueba que cada cifra citada coincide con la ficha del fondo.
  - Comprueba que ningun texto nombra un perfil distinto a {perfil}.
  - Comprueba que cada fondo encaja en una categoria permitida.
  - Si para algun criterio (ESG, sector) no hay encaje suficiente,
    dilo en el resumen ejecutivo. Es preferible recomendar 3 fondos
    buenos que 5 forzados.
"""


# Compatibilidad: prompt generico (sin perfil) para usos que importen la
# constante. El flujo normal usa build_system_prompt(perfil) en recommend().
SYSTEM_PROMPT = build_system_prompt()



def _fmt_pct(v: Any) -> str:
    """Formatea una fraccion como X,XX% para el prompt."""
    if v is None:
        return "n/d"
    try:
        return f"{float(v) * 100:.2f}%"
    except (TypeError, ValueError):
        return "n/d"


def _fmt_num(v: Any, decimales: int = 2) -> str:
    if v is None:
        return "n/d"
    try:
        return f"{float(v):.{decimales}f}"
    except (TypeError, ValueError):
        return "n/d"


def _record_to_brief(r: Dict[str, Any], expert: bool = False) -> str:
    """Convierte un registro a una linea compacta para el prompt.

    Incluye METRICAS CUANTITATIVAS de VDOS (r1a, ra3, sharpe, com_total,
    volatilidad) cuando estan presentes, para que el LLM elija con datos
    reales, no con intuicion. Estas claves vienen prefijadas _vdos_ del
    adaptador del backend de la web.
    """
    isin = r.get("ISIN", "")
    nombre = r.get("NFONDO", "")
    p20 = r.get("P20", "")
    p00 = r.get("P00", "")
    p05 = r.get("P05", "")
    p06 = r.get("P06", "")
    dminr = r.get("DMINR", "")
    garant = "GARANT=1" if r.get("GARANT") == 1 else ""
    gestora = r.get("P02", "")
    coment = (r.get("COMENT") or "")[:300]

    # Metricas cuantitativas VDOS (cuando estan)
    r1a = _fmt_pct(r.get("_vdos_r1a"))
    ra3 = _fmt_pct(r.get("_vdos_ra3"))
    sharpe = _fmt_num(r.get("_vdos_sharpe"))
    com_tot = _fmt_pct(r.get("_vdos_com_total"))
    vol = _fmt_pct(r.get("_vdos_volatilidad"))

    return (
        f"- [{isin}] {nombre}\n"
        f"  Gestora: {gestora}\n"
        f"  Categorias: P20={p20} | P00={p00} | P05={p05} | P06={p06}\n"
        f"  Plazo (DMINR): {dminr or '-'}{(' | ' + garant) if garant else ''}\n"
        f"  METRICAS VDOS: r1a={r1a} | ra3={ra3} | "
        f"Sharpe={sharpe} | com_total={com_tot} | volatilidad={vol}\n"
        f"  Politica: {coment}..."
    )


def _quality_score(r: Dict[str, Any]) -> float:
    """Score de calidad del fondo para pre-ordenar el universo.

    Combina Sharpe (mayor mejor) y comision (menor mejor). Fondos sin
    datos VDOS cuantitativos puntuan 0 y van al final. El LLM seguira
    decidiendo, pero ve primero los buenos.
    """
    sh = r.get("_vdos_sharpe")
    com = r.get("_vdos_com_total")
    if sh is None or not isinstance(sh, (int, float)):
        return -999.0  # al final
    score = float(sh)
    if isinstance(com, (int, float)):
        # Penaliza cada 0.5% de comision con 0.2 puntos
        score -= float(com) * 40.0  # 1% -> -0.4
    return score


def _filter_universe(
    records: List[Dict[str, Any]],
    profile: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Reduce el universo segun banco del gestor + restricciones duras
    del perfil + pre-orden por calidad cuantitativa.

    El LLM solo procesa 40 fondos. Si pasamos los mejores en Sharpe y
    comision PRIMERO, el LLM elige sobre los mejores."""
    out = list(records)

    # 1) Banco del gestor
    gestora_pref = (profile.get("gestora_propia") or "").strip()
    if gestora_pref:
        gestora_lower = gestora_pref.lower()
        own = [r for r in out if gestora_lower in str(r.get("P02", "")).lower()]
        if own:
            others = [r for r in out if r not in own]
            # Prioriza propios, completa con los mejores 10 de fuera
            others_sorted = sorted(others, key=_quality_score, reverse=True)[:10]
            out = own + others_sorted

    # 2) Exclusiones ESG
    excluir = profile.get("excluir") or []
    if excluir:
        ban = [e.lower() for e in excluir]
        out = [r for r in out
               if not any(b in (r.get("COMENT") or "").lower() for b in ban)]

    # 3) Descarta fondos con Sharpe muy negativo (basura cuantitativa)
    out_filtrado = []
    for r in out:
        sh = r.get("_vdos_sharpe")
        if isinstance(sh, (int, float)) and sh < -1.5:
            continue  # rentabilidad/riesgo malisima
        out_filtrado.append(r)
    out = out_filtrado if out_filtrado else out  # no vacies si todos malos

    # 4) Pre-orden por calidad cuantitativa (mejor Sharpe ajustado primero)
    out = sorted(out, key=_quality_score, reverse=True)

    return out


def _profile_to_prompt(profile: Dict[str, Any]) -> str:
    lines = ["=== PERFIL DEL CLIENTE ==="]
    keymap = [
        ("Nombre", "nombre"),
        ("Edad", "edad"),
        ("País / residencia", "pais"),
        ("Renta anual estimada", "renta"),
        ("Capital disponible para invertir (€)", "capital"),
        ("Aportaciones mensuales (€)", "aportacion_mensual"),
        ("Horizonte temporal", "horizonte"),
        ("Perfil de riesgo", "perfil_riesgo"),
        ("Sectores preferidos", "sectores"),
        ("Regiones preferidas", "regiones"),
        ("Restricciones éticas / ESG", "esg"),
        ("Exclusiones", "excluir"),
        ("Notas del gestor", "notas"),
    ]
    for label, key in keymap:
        v = profile.get(key)
        if v in (None, "", [], 0):
            continue
        if isinstance(v, list):
            v = ", ".join(v)
        lines.append(f"  - {label}: {v}")
    gestora = profile.get("gestora_propia")
    if gestora:
        lines.append(f"  - Banco/Gestora del gestor: {gestora}  "
                     f"(prioriza fondos de esta gestora)")
    return "\n".join(lines)


def _universe_to_prompt(records: List[Dict[str, Any]]) -> str:
    lines = ["=== UNIVERSO DE FONDOS DISPONIBLES ==="]
    for r in records[:40]:  # cap de seguridad
        lines.append(_record_to_brief(r))
    return "\n\n".join(lines)


_JSON_SCHEMA_HINT = """\
=== FORMATO DE RESPUESTA ===
Responde UNICAMENTE con un objeto JSON valido con estas claves:
{
  "resumen_ejecutivo": "Parrafo de 2-4 frases para el gestor explicando la asignacion global.",
  "fondos_recomendados": [
    {
      "isin": "ESXXXXXXXXXX",
      "nombre": "Nombre del fondo tal como esta en el catalogo",
      "peso_cartera_pct": 40,
      "justificacion": "Por que este fondo encaja con este cliente concreto."
    }
  ],
  "cartera_modelo": {
    "descripcion": "Resumen de la distribucion global",
    "asignacion": [
      {"bloque": "RV Internacional USA", "peso_pct": 40, "isins": ["ESXX..."]},
      {"bloque": "RF Euro Corto Plazo", "peso_pct": 30, "isins": ["ESXX..."]}
    ]
  },
  "riesgos_y_advertencias": "Riesgos relevantes a comunicar al cliente."
}

Los pesos deben sumar 100. Devuelve entre 3 y 5 fondos.
NO incluyas markdown, NO bloques de codigo. Solo el JSON.
"""


def _build_user_prompt(profile: Dict[str, Any],
                      records: List[Dict[str, Any]]) -> str:
    return (
        f"{_profile_to_prompt(profile)}\n\n"
        f"{_universe_to_prompt(records)}\n\n"
        f"{_JSON_SCHEMA_HINT}"
    )


def recommend(
    profile: Dict[str, Any],
    records: List[Dict[str, Any]],
    model: str = _DEFAULT_MODEL,
) -> Dict[str, Any]:
    """Llama al LLM y devuelve la recomendacion estructurada.

    Si el LLM responde mal, levanta excepcion con el texto crudo."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY no definida.")
    universo = _filter_universe(records, profile)
    if not universo:
        raise ValueError(
            "Universo vacio tras filtrar. Revisa banco/exclusiones."
        )
    user_prompt = _build_user_prompt(profile, universo)
    system_prompt = build_system_prompt(profile.get("perfil_riesgo"))

    from openai import OpenAI
    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Respuesta no es JSON valido: {e}\n\nRaw:\n{raw}")

    # Enriquecer cada fondo con metadata del catalogo (para render local)
    by_isin = {r["ISIN"]: r for r in records}
    enriched = []
    for f in data.get("fondos_recomendados", []):
        rec = dict(by_isin.get(f.get("isin"), {}))
        f["_record"] = rec
        enriched.append(f)
    data["fondos_recomendados"] = enriched
    data["_universe_size"] = len(universo)
    return data
