r"""
streamlit_app.py — VDOS Funds Explorer.

4 pestañas:
    Inicio       Landing + KPIs + dashboard
    Chat         RAG con gpt-4o-mini para preguntas libres
    Comparador   2 fondos lado a lado (+ placeholder grafico VLP)
    Asesor IA    Perfil de cliente -> recomendacion + cartera modelo

Sidebar:
    - Logo + titulo
    - Selector "Yo soy gestor de X" (prioriza fondos de esa gestora)
    - Modo experto (codigos VDOS)
    - Filtros aplicables a Chat y Comparador
    - Estado del indice + Re-indexar

Pre-requisitos:
    $env:OPENAI_API_KEY = "sk-proj-..."
    python -m rag.index ..\pdfs_extracted.json --reset
"""

from __future__ import annotations
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, Any, List

import streamlit as st
import pandas as pd

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

_DBG = _REPO / "debug.log"


def _log(msg: str) -> None:
    try:
        with open(_DBG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")
    except Exception:
        pass


_log("=== app: start ===")

from rag.embed import EmbeddingClient  # noqa: E402
from rag.index import index_json, _CHROMA_DIR  # noqa: E402
from rag.chat import answer, retrieve, extract_cited_isins  # noqa: E402
from rag.labels import code_to_label, display  # noqa: E402
from rag.advisor import recommend  # noqa: E402
from rag.news import (  # noqa: E402
    get_positive_news,
    topics_from_recommendation,
)
from rag import simple_store  # noqa: E402

_log("imports OK")

DEFAULT_JSON = _REPO / "pdfs_extracted.json"
LOGO_PATH = _HERE / "static" / "logo.png"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_records(path: str) -> List[Dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _index_ready() -> bool:
    return "error" not in simple_store.status()


def _index_status() -> Dict[str, Any]:
    return simple_store.status()


def _filter_records(records: List[Dict[str, Any]],
                    filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for r in records:
        keep = True
        for k, v in filters.items():
            rv = r.get(k)
            if isinstance(v, list):
                if rv not in v:
                    keep = False
                    break
            else:
                if rv != v:
                    keep = False
                    break
        if keep:
            out.append(r)
    return out


def _safe_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in df.columns:
        df[c] = df[c].apply(lambda x: "" if x is None else str(x))
    return df


def _highlight_match(text: str, query: str, max_chars: int = 280) -> str:
    if not text:
        return ""
    if not query:
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    tl = text.lower()
    for w in query.lower().split():
        if len(w) >= 4:
            i = tl.find(w)
            if i >= 0:
                start = max(0, i - 80)
                end = min(len(text), i + max_chars - 80)
                snippet = text[start:end]
                if start > 0:
                    snippet = "..." + snippet
                if end < len(text):
                    snippet = snippet + "..."
                return snippet
    return text[:max_chars] + ("..." if len(text) > max_chars else "")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
def render_sidebar(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    with st.sidebar:
        if LOGO_PATH.exists():
            try:
                st.image(str(LOGO_PATH), width=110)
            except Exception as e:
                _log(f"st.image FAIL: {e}")
        st.markdown("### VDOS Funds Explorer")
        st.caption("Análisis y asesoramiento de fondos CNMV")
        st.divider()

        # Selector banco/gestora del gestor
        gestoras_labels = sorted({
            code_to_label("P02", r["P02"]) for r in records if r.get("P02")
        })
        gestoras_labels = ["— Sin gestora —"] + gestoras_labels
        gestora_propia = st.selectbox(
            "Yo soy gestor de…",
            options=gestoras_labels,
            help="Prioriza fondos de esta gestora en Chat y Asesor IA",
        )
        if gestora_propia == "— Sin gestora —":
            gestora_propia = ""

        expert = st.toggle(
            "Modo experto",
            value=False,
            help="Muestra códigos VDOS (P02_GXXXX, P00_GX…)",
        )

        with st.expander("Filtros", expanded=False):
            gestoras = sorted({r["P02"] for r in records if r.get("P02")})
            p00s = sorted({r["P00"] for r in records if r.get("P00")})
            p05s = sorted({r["P05"] for r in records if r.get("P05")})
            p06s = sorted({r["P06"] for r in records if r.get("P06")})

            def _opts(values, var):
                try:
                    return {v: code_to_label(var, v) for v in values}
                except Exception:
                    return {v: v for v in values}

            opt_g = _opts(gestoras, "P02")
            opt_p00 = _opts(p00s, "P00")
            opt_p05 = _opts(p05s, "P05")
            opt_p06 = _opts(p06s, "P06")

            sel_g = st.multiselect(
                "Gestora", list(opt_g.keys()),
                format_func=lambda x: opt_g.get(x, x),
            )
            sel_p00 = st.multiselect(
                "Categoría VDOS", list(opt_p00.keys()),
                format_func=lambda x: opt_p00.get(x, x),
            )
            sel_p05 = st.multiselect(
                "Región / divisa", list(opt_p05.keys()),
                format_func=lambda x: opt_p05.get(x, x),
            )
            sel_p06 = st.multiselect(
                "Sector / activo", list(opt_p06.keys()),
                format_func=lambda x: opt_p06.get(x, x),
            )
            only_garant = st.checkbox("Solo garantizados")

        st.divider()
        st.caption("Estado del índice")
        s = _index_status()
        if "error" in s:
            st.warning(s["error"])
        else:
            st.success(
                f"Índice listo · {s.get('count', 0)} docs · "
                f"{s.get('size_kb', 0)} KB"
            )
            st.caption(f"Modelo embed: `{s.get('model', '-')}`")

        with st.expander("Configuración", expanded=False):
            json_path = st.text_input("Ruta del JSON", value=str(DEFAULT_JSON))
            if st.button("Re-indexar", use_container_width=True):
                try:
                    with st.spinner("Re-indexando..."):
                        stats = index_json(json_path, reset=True)
                    st.success(
                        f"Indexados {stats['indexed']} ISINs "
                        f"({stats['provider']}/{stats['model']})"
                    )
                except Exception as e:
                    st.error(f"Error: {e}")
            st.caption(f"Store: `{_CHROMA_DIR}`")

    filters: Dict[str, Any] = {}
    if sel_g:
        filters["P02"] = sel_g
    if sel_p00:
        filters["P00"] = sel_p00
    if sel_p05:
        filters["P05"] = sel_p05
    if sel_p06:
        filters["P06"] = sel_p06
    if only_garant:
        filters["GARANT"] = 1
    return {
        "filters": filters,
        "expert": expert,
        "gestora_propia": gestora_propia,
    }


# ---------------------------------------------------------------------------
# Pestaña: Inicio
# ---------------------------------------------------------------------------
def tab_home(records: List[Dict[str, Any]], expert: bool) -> None:
    st.markdown(
        "### Bienvenido a **VDOS Funds Explorer**  \n"
        "Herramienta de análisis y asesoramiento de fondos CNMV para "
        "gestores y analistas."
    )

    st.markdown("#### ¿Qué puedes hacer aquí?")
    c1, c2, c3 = st.columns(3)
    c1.markdown(
        "**Chat**  \n"
        "Pregunta libre sobre el catálogo. La IA busca y responde con los "
        "fondos que mejor encajan con la consulta."
    )
    c2.markdown(
        "**Comparador**  \n"
        "Selecciona dos fondos y compáralos lado a lado. Comisiones, "
        "categorías, política y (próximamente) histórico de VLP."
    )
    c3.markdown(
        "**Asesor IA**  \n"
        "Introduce el perfil del cliente (edad, riesgo, horizonte, "
        "preferencias) y la IA recomienda fondos con justificación y "
        "cartera modelo."
    )

    st.divider()
    st.subheader("Estado del catálogo")
    from collections import Counter
    n_total = len(records)
    n_garant = sum(1 for r in records if r.get("GARANT") == 1)
    n_gest = len({r.get("P02") for r in records if r.get("P02")})
    n_p00 = len({r.get("P00") for r in records if r.get("P00")})
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("ISINs", n_total)
    k2.metric("Gestoras", n_gest)
    k3.metric("Categorías VDOS", n_p00)
    k4.metric("Garantizados", n_garant)

    st.divider()
    cA, cB = st.columns(2)
    with cA:
        st.markdown("##### Distribución por categoría VDOS (P00)")
        c = Counter(r.get("P00") for r in records if r.get("P00"))
        if c:
            df = pd.DataFrame([
                {"Categoría": code_to_label("P00", k) if not expert
                              else f"{k} — {code_to_label('P00', k)}",
                 "ISINs": v}
                for k, v in sorted(c.items(), key=lambda x: -x[1])
            ])
            st.bar_chart(df.set_index("Categoría"))
    with cB:
        st.markdown("##### Distribución por gestora")
        c = Counter(r.get("P02") for r in records if r.get("P02"))
        if c:
            df = pd.DataFrame([
                {"Gestora": code_to_label("P02", k) if not expert else k,
                 "ISINs": v}
                for k, v in sorted(c.items(), key=lambda x: -x[1])
            ])
            st.bar_chart(df.set_index("Gestora"))


# ---------------------------------------------------------------------------
# Pestaña: Chat
# ---------------------------------------------------------------------------
def _render_msg(msg: Dict[str, Any], expert: bool) -> None:
    label = "Tú" if msg.get("role") == "user" else "Asistente"
    with st.container(border=True):
        st.markdown(f"**{label}**")
        st.markdown(msg.get("content", ""))
        cited = msg.get("cited") or []
        if cited:
            with st.expander(f"{len(cited)} fondos citados"):
                for r in cited:
                    st.markdown(
                        f"- **{r.get('NFONDO','')}** "
                        f"`{r['ISIN']}` — "
                        f"{display(r, 'P00', expert)} · "
                        f"{display(r, 'P05', expert)} · "
                        f"{display(r, 'P06', expert)}"
                    )


def tab_chat(records: List[Dict[str, Any]],
             filters: Dict[str, Any],
             expert: bool,
             gestora_propia: str) -> None:
    st.subheader("Chat IA · gpt-4o-mini")
    st.caption(
        "Pregunta libre sobre los fondos del catálogo. La IA busca con "
        "embeddings y responde citando ISINs."
    )
    if not _index_ready():
        st.warning("Sin índice. Re-indexa desde la sidebar.")
        return
    if not os.environ.get("OPENAI_API_KEY"):
        st.error("Falta OPENAI_API_KEY en el entorno.")
        return

    info_chips = []
    if filters:
        info_chips.append(f"{len(filters)} filtro(s) activos")
    if gestora_propia:
        info_chips.append(f"Gestor de: {gestora_propia}")
    if info_chips:
        st.caption(" · ".join(info_chips))

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    cols = st.columns([1, 1, 1, 2])
    top_k = cols[0].slider("Top K", 3, 15, 5)
    model = cols[1].selectbox("Modelo", ["gpt-4o-mini", "gpt-4o"], index=0)
    if cols[2].button("Limpiar", use_container_width=True):
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        _render_msg(msg, expert)

    with st.form("chat_form", clear_on_submit=True):
        user_q = st.text_area(
            "Pregunta",
            placeholder="¿Qué fondos invierten en tecnología en EE.UU.?",
            height=80,
            label_visibility="collapsed",
        )
        submit = st.form_submit_button("Enviar", type="primary")

    if not (submit and user_q.strip()):
        return

    st.session_state.chat_history.append({
        "role": "user", "content": user_q.strip()
    })
    _render_msg(st.session_state.chat_history[-1], expert)

    with st.spinner("Pensando…"):
        try:
            text, hits = answer(
                user_q.strip(),
                top_k=top_k,
                filters=filters or None,
                model=model,
                extra_records=records,
            )
        except Exception as e:
            st.error(f"Error: {e}")
            st.code(traceback.format_exc())
            return

    cited_isins = set(extract_cited_isins(text))
    cited = [r for r in hits if r["ISIN"] in cited_isins] or hits
    msg = {"role": "assistant", "content": text, "cited": cited}
    st.session_state.chat_history.append(msg)
    _render_msg(msg, expert)


# ---------------------------------------------------------------------------
# Pestaña: Comparador
# ---------------------------------------------------------------------------
_COMPARE_KEYS = ["ISIN", "NFONDO", "P02", "P11", "AUDITOR", "P01", "P20",
                 "P00", "P05", "P06", "INFOREFB", "DMINR", "GARANT",
                 "FVENGAR", "DIVISA", "APMIN", "MINIMANT",
                 "COMIGEST", "SCOMIG", "COMIDEPO", "SCOMID",
                 "COMIAPEX", "SCOMIA", "COMIREEX", "SCOMIR",
                 "TIPO", "SHARE"]


def tab_compare(records: List[Dict[str, Any]], expert: bool) -> None:
    st.subheader("Comparador de dos fondos")
    options = [f"{r['ISIN']} - {r.get('NFONDO','')}" for r in records]
    c1, c2 = st.columns(2)
    a = c1.selectbox("Fondo A", options, index=0)
    b = c2.selectbox("Fondo B", options, index=min(1, len(options)-1))
    ra = next(r for r in records if r["ISIN"] == a.split(" - ", 1)[0])
    rb = next(r for r in records if r["ISIN"] == b.split(" - ", 1)[0])

    rows = []
    for k in _COMPARE_KEYS:
        va, vb = ra.get(k), rb.get(k)
        if isinstance(va, str) and any(va.startswith(p) for p in (
                "P02_", "P11_", "P00_", "P05_", "P06_")):
            va_s = display(ra, k, expert)
            vb_s = display(rb, k, expert)
        else:
            va_s = "" if va is None else str(va)
            vb_s = "" if vb is None else str(vb)
        rows.append({
            "Campo": k, "A": va_s, "B": vb_s,
            "≠": "" if va == vb else "≠",
        })
    st.dataframe(_safe_df(rows), hide_index=True, use_container_width=True)

    st.divider()
    st.markdown("##### Comisiones lado a lado")
    comm_rows = []
    for label, k in (("Gestión", "COMIGEST"), ("Depositario", "COMIDEPO"),
                     ("Suscripción", "COMIAPEX"), ("Reembolso", "COMIREEX")):
        comm_rows.append({"Concepto": label,
                          "A (%)": ra.get(k, 0.0),
                          "B (%)": rb.get(k, 0.0)})
    df_c = pd.DataFrame(comm_rows).set_index("Concepto")
    st.bar_chart(df_c)

    st.divider()
    st.markdown("##### Histórico VLP (Valor Liquidativo)")
    with st.container(border=True):
        st.info(
            "**Próximamente.** Cuando esté disponible el acceso a la "
            "base de datos de VLP de VDOS, aquí se pintará el gráfico "
            "histórico comparado de los dos fondos seleccionados."
        )

    cA, cB = st.columns(2)
    with cA:
        with st.expander("Política A"):
            st.write(ra.get("COMENT") or "_(vacío)_")
    with cB:
        with st.expander("Política B"):
            st.write(rb.get("COMENT") or "_(vacío)_")


# ---------------------------------------------------------------------------
# Pestaña: Asesor IA
# ---------------------------------------------------------------------------
_HORIZONTES = ["< 1 año", "1-3 años", "3-5 años", "5-10 años",
               "> 10 años", "Jubilación"]
_RENTAS = ["No declarado", "< 30.000 €", "30.000 - 60.000 €",
           "60.000 - 100.000 €", "100.000 - 200.000 €", "> 200.000 €"]
_SECTORES = ["Tecnología", "Salud", "Financiero", "Energía",
             "Materias primas", "Consumo", "Inmobiliario",
             "Renta Fija pública", "Renta Fija privada",
             "Renta Variable global", "ESG / Sostenibilidad",
             "Sin preferencia"]
_REGIONES = ["España / Iberia", "Zona Euro", "EE.UU. / Norteamérica",
             "Reino Unido", "Japón", "Emergentes Asia",
             "Emergentes Latinoamérica", "Global", "Sin preferencia"]
_EXCLUSIONES = ["Armas", "Tabaco", "Combustibles fósiles",
                "Apuestas / juego", "Pornografía", "Ninguna"]


def _build_profile_form() -> Dict[str, Any]:
    """Renderiza el formulario y devuelve el dict de perfil."""
    with st.form("advisor_form"):
        st.markdown("#### Identidad (opcional)")
        c1, c2, c3 = st.columns(3)
        nombre = c1.text_input("Nombre", value="")
        apellidos = c2.text_input("Apellidos", value="")
        dni = c3.text_input("DNI / Identificador", value="")

        st.markdown("#### Demografía")
        c1, c2, c3 = st.columns(3)
        edad = c1.slider("Edad", 18, 90, 45)
        pais = c2.text_input("País de residencia", value="España")
        renta = c3.selectbox("Renta anual", _RENTAS, index=0)

        st.markdown("#### Capacidad de inversión")
        c1, c2, c3 = st.columns(3)
        capital = c1.number_input(
            "Capital disponible (€)", min_value=0, value=50000, step=1000,
        )
        aportacion = c2.number_input(
            "Aportaciones mensuales (€)", min_value=0, value=0, step=50,
        )
        horizonte = c3.selectbox(
            "Horizonte temporal", _HORIZONTES, index=3,
        )

        st.markdown("#### Perfil de riesgo")
        perfil_riesgo = st.radio(
            "Tolerancia al riesgo",
            ["Conservador", "Moderado", "Agresivo"],
            index=1,
            horizontal=True,
        )

        st.markdown("#### Preferencias (opcional)")
        c1, c2 = st.columns(2)
        sectores = c1.multiselect("Sectores preferidos", _SECTORES)
        regiones = c2.multiselect("Regiones preferidas", _REGIONES)

        st.markdown("#### Restricciones éticas / ESG (opcional)")
        excluir = st.multiselect(
            "Exclusiones",
            _EXCLUSIONES,
            help="Sectores/temas a evitar",
        )

        st.markdown("#### Notas del gestor (opcional)")
        notas = st.text_area(
            "Notas",
            placeholder="Comentarios libres, contexto del cliente, "
                        "objetivos específicos…",
            height=80,
        )

        submit = st.form_submit_button("Generar recomendación", type="primary")

    if not submit:
        return {}

    return {
        "nombre": (f"{nombre} {apellidos}".strip() or None),
        "dni": dni or None,
        "edad": edad,
        "pais": pais,
        "renta": None if renta == "No declarado" else renta,
        "capital": capital,
        "aportacion_mensual": aportacion,
        "horizonte": horizonte,
        "perfil_riesgo": perfil_riesgo,
        "sectores": sectores,
        "regiones": regiones,
        "excluir": [e for e in excluir if e and e != "Ninguna"],
        "notas": notas or None,
    }


def _render_recommendation(rec: Dict[str, Any], expert: bool) -> None:
    st.success("Recomendación generada")

    resumen = rec.get("resumen_ejecutivo")
    if resumen:
        st.markdown("### Resumen ejecutivo")
        st.write(resumen)

    fondos = rec.get("fondos_recomendados") or []
    if fondos:
        st.markdown("### Fondos recomendados")
        # Cartera modelo pie chart
        pesos = [{"Fondo": f.get("nombre", f.get("isin", "?"))[:40],
                  "Peso %": f.get("peso_cartera_pct", 0)}
                 for f in fondos]
        df_pesos = pd.DataFrame(pesos)
        if not df_pesos.empty and df_pesos["Peso %"].sum() > 0:
            st.bar_chart(df_pesos.set_index("Fondo"))

        for i, f in enumerate(fondos, 1):
            r = f.get("_record") or {}
            isin = f.get("isin", "?")
            nombre = f.get("nombre", r.get("NFONDO", ""))
            peso = f.get("peso_cartera_pct", "?")
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"**{i}. {nombre}**  \n`{isin}`")
                c2.metric("Peso", f"{peso}%")
                st.caption(
                    f"P00: {display(r, 'P00', expert)} · "
                    f"P05: {display(r, 'P05', expert)} · "
                    f"P06: {display(r, 'P06', expert)} · "
                    f"Gestora: {display(r, 'P02', expert)} · "
                    f"Comisión: {r.get('SCOMIG', '-')}"
                )
                st.markdown(
                    f"**Por qué encaja:** {f.get('justificacion', '-')}"
                )

    # Tabla comparativa
    if fondos:
        st.markdown("### Tabla comparativa")
        rows = []
        for f in fondos:
            r = f.get("_record") or {}
            rows.append({
                "ISIN": f.get("isin"),
                "Nombre": (f.get("nombre") or r.get("NFONDO", ""))[:50],
                "Gestora": display(r, "P02", expert),
                "P00": display(r, "P00", expert),
                "Plazo": r.get("DMINR", "-"),
                "Gestión": r.get("SCOMIG", "-"),
                "Depositario": r.get("SCOMID", "-"),
                "Peso cartera": f"{f.get('peso_cartera_pct', '?')}%",
            })
        st.dataframe(_safe_df(rows), hide_index=True, use_container_width=True)

    # Cartera modelo
    cartera = rec.get("cartera_modelo")
    if cartera:
        st.markdown("### Cartera modelo")
        desc = cartera.get("descripcion")
        if desc:
            st.write(desc)
        asignacion = cartera.get("asignacion") or []
        if asignacion:
            df = pd.DataFrame([
                {"Bloque": b.get("bloque"),
                 "Peso %": b.get("peso_pct"),
                 "ISINs": ", ".join(b.get("isins") or [])}
                for b in asignacion
            ])
            st.dataframe(_safe_df(df.to_dict("records")),
                         hide_index=True, use_container_width=True)

    riesgos = rec.get("riesgos_y_advertencias")
    if riesgos:
        st.markdown("### Riesgos y advertencias")
        st.warning(riesgos)

    with st.expander("Datos crudos de la IA (JSON)"):
        st.json({k: v for k, v in rec.items() if not k.startswith("_")})


def _render_news_section(rec: Dict[str, Any],
                         profile: Dict[str, Any]) -> None:
    """Tras la recomendacion, ofrece 5 noticias positivas por tema relevante.

    Las queries se derivan de la recomendacion (sectores del perfil + P06 de
    los fondos recomendados + bloques de la cartera modelo). El usuario puede
    elegir el tema y refinar el termino. La clasificacion positivo/neutral/
    negativo la hace gpt-4o-mini sobre los titulares descargados de Google
    Noticias por RSS."""
    st.divider()
    st.markdown("### Noticias relacionadas")
    st.caption(
        "Titulares recientes de Google Noticias relacionados con la "
        "recomendación. Se priorizan las 5 noticias **positivas** del "
        "tema seleccionado."
    )

    temas = topics_from_recommendation(rec, profile, max_topics=6)
    if not temas:
        st.info("No se han podido derivar temas relevantes de la recomendación.")
        return

    labels = [t["label"] for t in temas] + ["Otro (escribir término libre)"]
    col_a, col_b, col_c = st.columns([2, 2, 1])
    sel = col_a.selectbox("Tema", labels, index=0,
                          key="news_topic_selectbox")
    if sel == "Otro (escribir término libre)":
        query = col_b.text_input(
            "Término de búsqueda",
            value="materias primas",
            key="news_topic_freetext",
        )
    else:
        default_q = next((t["query"] for t in temas if t["label"] == sel),
                         sel)
        query = col_b.text_input(
            "Término de búsqueda",
            value=default_q,
            key="news_topic_query",
        )
    use_llm = col_c.toggle(
        "Filtrar positivas (IA)",
        value=bool(os.environ.get("OPENAI_API_KEY")),
        help="Usa gpt-4o-mini para clasificar el sentimiento y priorizar "
             "noticias positivas. Si se desactiva, se muestran las 5 más "
             "recientes.",
        key="news_use_llm",
    )

    if not query or not query.strip():
        st.info("Introduce un término de búsqueda.")
        return

    with st.spinner(f"Buscando noticias sobre **{query}**…"):
        try:
            items = get_positive_news(
                query.strip(),
                max_results=5,
                pool_size=20,
                classify=use_llm,
            )
        except Exception as e:
            st.error(f"No se pudieron obtener noticias: {e}")
            return

    if not items:
        st.warning("Sin resultados. Prueba otro término.")
        return

    badge_map = {
        "positivo": ("[+]", "Positiva"),
        "neutral":  ("[=]", "Neutral"),
        "negativo": ("[-]", "Negativa"),
    }
    for n in items:
        title = n.get("title") or "(sin título)"
        link = n.get("link") or ""
        source = n.get("source") or ""
        published = n.get("published") or ""
        summary = n.get("summary") or ""
        sentiment = n.get("sentiment")
        with st.container(border=True):
            head = f"**[{title}]({link})**" if link else f"**{title}**"
            st.markdown(head)
            meta = []
            if source:
                meta.append(source)
            if published:
                meta.append(published)
            if sentiment and sentiment in badge_map:
                emoji, label_s = badge_map[sentiment]
                meta.append(f"{emoji} {label_s}")
            if meta:
                st.caption(" · ".join(meta))
            if summary:
                st.write(summary[:300] + ("…" if len(summary) > 300 else ""))


def tab_advisor(records: List[Dict[str, Any]],
                expert: bool,
                gestora_propia: str) -> None:
    st.subheader("Asesor IA al gestor")
    st.caption(
        "Introduce el perfil del cliente y la IA recomendará fondos del "
        "catálogo con justificación, comparativa y cartera modelo."
    )
    if not os.environ.get("OPENAI_API_KEY"):
        st.error("Falta OPENAI_API_KEY en el entorno.")
        return

    if gestora_propia:
        st.info(
            f"Como gestor de **{gestora_propia}**, la IA priorizará "
            "fondos de esta gestora y mencionará alternativas similares."
        )

    profile = _build_profile_form()

    if profile:
        profile["gestora_propia"] = gestora_propia or None
        with st.expander("Perfil enviado al modelo"):
            st.json(profile)

        with st.spinner("La IA está analizando el catálogo y elaborando la recomendación…"):
            try:
                rec = recommend(profile, records)
            except Exception as e:
                st.error(f"Error en el asesor: {e}")
                st.code(traceback.format_exc())
                return

        st.session_state["last_recommendation"] = rec
        st.session_state["last_profile"] = profile

    # Si tenemos una recomendacion (recien generada o de un rerun anterior),
    # la pintamos junto con la seccion de noticias.
    rec = st.session_state.get("last_recommendation")
    last_profile = st.session_state.get("last_profile") or {}
    if not rec:
        return
    _render_recommendation(rec, expert)
    _render_news_section(rec, last_profile)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def main() -> None:
    _log("main inicio")
    st.set_page_config(
        page_title="VDOS Funds Explorer",
        layout="wide",
    )
    _log("page_config OK")

    json_path = str(DEFAULT_JSON)
    if not Path(json_path).exists():
        st.error(f"No encuentro {json_path}.")
        return
    _log("json path OK")

    records = _load_records(json_path)
    _log(f"records loaded ({len(records)})")

    state = render_sidebar(records)
    _log("sidebar OK")
    expert = state["expert"]
    filters = state["filters"]
    gestora_propia = state["gestora_propia"]

    st.title("VDOS Funds Explorer")
    st.caption(
        f"{len(records)} ISINs · "
        f"{'modo experto' if expert else 'modo cliente'}"
        f"{' · filtros activos' if filters else ''}"
        f"{' · gestor de ' + gestora_propia if gestora_propia else ''}"
    )
    _log("title OK")

    tabs = st.tabs(["Inicio", "Chat", "Comparador", "Asesor IA"])
    _log("tabs created")
    with tabs[0]:
        tab_home(records, expert)
        _log("tab_home OK")
    with tabs[1]:
        tab_chat(records, filters, expert, gestora_propia)
        _log("tab_chat OK")
    with tabs[2]:
        tab_compare(_filter_records(records, filters), expert)
        _log("tab_compare OK")
    with tabs[3]:
        tab_advisor(records, expert, gestora_propia)
        _log("tab_advisor OK")
    _log("=== main END ===")


# Streamlit ejecuta el script directamente; main() debe llamarse sin guardas.
main()
