// estudio.js — Logica de la vista Estudio comparativo VDOS vs ChatGPT.

import { api } from '../api.js';

const $ = (sel) => document.querySelector(sel);

const state = {
  perfiles: [],
  perfilActivo: null,
};

function escapeHTML(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

// ---------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------
async function init() {
  try {
    // Conteo real de folletos del catalogo (servido por la API), nunca fijo.
    api.stats().then((s) => {
      const el = $('#count-folletos');
      if (el && typeof s.isins === 'number') {
        el.textContent = s.isins.toLocaleString('es-ES');
      }
    }).catch(() => {});

    const perfiles = await api.estudioPerfiles();
    state.perfiles = perfiles;
    renderPerfilChips();
    if (perfiles.length) {
      await selectPerfil(perfiles[0].id);
    }
    await loadAgregado();
  } catch (e) {
    $('#perfil-chip-row').innerHTML =
      `<span class="text-sm" style="color: var(--loss-700)">Error: ${escapeHTML(e.message)}</span>`;
  }
}

// ---------------------------------------------------------------------
// Selector de perfil
// ---------------------------------------------------------------------
function renderPerfilChips() {
  const row = $('#perfil-chip-row');
  row.innerHTML = '';
  state.perfiles.forEach((p) => {
    const chip = document.createElement('span');
    chip.className = 'perfil-chip';
    chip.dataset.id = p.id;
    chip.textContent = p.etiqueta;
    chip.addEventListener('click', () => selectPerfil(p.id));
    row.appendChild(chip);
  });
}

async function selectPerfil(id) {
  state.perfilActivo = id;
  document.querySelectorAll('.perfil-chip').forEach((c) => {
    c.classList.toggle('active', c.dataset.id === id);
  });
  await renderComparativa();
}

// ---------------------------------------------------------------------
// Render principal
// ---------------------------------------------------------------------
async function renderComparativa() {
  if (!state.perfilActivo) return;
  let data;
  try {
    data = await api.estudioComparativa(state.perfilActivo);
  } catch (e) {
    setStatus('paste-status', e.message, true);
    return;
  }

  renderPerfilDetail(data.perfil);
  renderPromptBox(data.prompt_chatgpt);
  $('#prompt-section').classList.remove('hidden');
  $('#paste-section').classList.remove('hidden');
  $('#run-section').classList.remove('hidden');
  $('#comparison-section').classList.remove('hidden');
  bindActionsForPerfil(data.perfil.id);

  renderSystemSide('asesor', data.asesor_vdos);
  renderSystemSide('chatgpt', data.chatgpt);

  if (data.asesor_vdos || data.chatgpt) {
    $('#bars-section').classList.remove('hidden');
    renderBars(data.asesor_vdos, data.chatgpt);
    await loadPanelAvanzado(state.perfilActivo);
  } else {
    $('#bars-section').classList.add('hidden');
    $('#panel-avanzado-section').classList.add('hidden');
    $('#metodologia-section').classList.add('hidden');
  }
}

// ---------------------------------------------------------------------
// Panel avanzado: radar objetivo + Kappa de Cohen
// ---------------------------------------------------------------------
async function loadPanelAvanzado(perfilId) {
  try {
    const data = await api.estudioPanelAvanzado(perfilId);
    if (!data.has_asesor && !data.has_chatgpt) {
      $('#panel-avanzado-section').classList.add('hidden');
      $('#metodologia-section').classList.add('hidden');
      return;
    }
    $('#panel-avanzado-section').classList.remove('hidden');
    $('#metodologia-section').classList.remove('hidden');
    renderRadarObjetivo(data.radar_objetivo);
    renderKappaTable(data.kappa);
  } catch (e) {
    console.error('panel avanzado', e);
  }
}

function renderRadarObjetivo(radar) {
  const ejes = radar.ejes;
  const labels = ejes.map((e) => e.label);
  const valoresA = ejes.map((e) => radar.asesor[e.key]);
  const valoresB = ejes.map((e) => radar.chatgpt[e.key]);

  // Plotly necesita cerrar el poligono repitiendo el primer punto
  const closeRadar = (arr) => [...arr, arr[0]];
  const closeLabels = (arr) => [...arr, arr[0]];

  Plotly.react('radar-objetivo', [
    {
      type: 'scatterpolar',
      r: closeRadar(valoresA),
      theta: closeLabels(labels),
      fill: 'toself',
      name: 'Asesor VDOS',
      line: { color: '#042C53', width: 2 },
      fillcolor: 'rgba(4, 44, 83, 0.2)',
    },
    {
      type: 'scatterpolar',
      r: closeRadar(valoresB),
      theta: closeLabels(labels),
      fill: 'toself',
      name: 'ChatGPT',
      line: { color: '#10A37F', width: 2 },
      fillcolor: 'rgba(16, 163, 127, 0.2)',
    },
  ], {
    polar: {
      radialaxis: { visible: true, range: [0, 100], tickfont: { size: 10 } },
      angularaxis: { tickfont: { size: 11 } },
    },
    margin: { l: 60, r: 60, t: 30, b: 30 },
    paper_bgcolor: '#FFFFFF',
    plot_bgcolor: '#FFFFFF',
    font: { family: 'Inter, system-ui, sans-serif', size: 12, color: '#042C53' },
    legend: { orientation: 'h', y: -0.1 },
    showlegend: true,
  }, { displayModeBar: false, responsive: true });
}

function renderKappaTable(kappa) {
  // Resumen arriba
  const summary = $('#kappa-summary');
  const kGlobal = kappa.kappa_global;
  const interp = kappa.interpretacion_global;
  summary.innerHTML = `
    <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
      <div class="metric-card">
        <div class="metric-label">Fondos Asesor</div>
        <div class="metric-value mono">${kappa.n_fondos_asesor}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Fondos ChatGPT</div>
        <div class="metric-value mono">${kappa.n_fondos_chatgpt}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Comunes / Unión</div>
        <div class="metric-value mono">${kappa.n_fondos_comunes} / ${kappa.n_fondos_union}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Solapamiento (Jaccard)</div>
        <div class="metric-value mono">${(kappa.jaccard !== null && kappa.jaccard !== undefined) ? kappa.jaccard.toFixed(2) : '—'}</div>
        <div class="metric-help">${kappa.n_fondos_comunes === 0 ? 'carteras disjuntas (κ de acuerdo no aplicable)' : 'fracción de fondos compartidos'}</div>
      </div>
    </div>
  `;

  const wrap = $('#kappa-table-wrap');
  if (!kappa.items || kappa.items.length === 0) {
    wrap.innerHTML = '<div class="empty">No hay items pareados (faltan recomendaciones de uno de los sistemas).</div>';
    return;
  }
  const fmt = (v, d = 3) => (v === null || v === undefined) ? '—' : v.toFixed(d);
  const interpCls = (i) => {
    const map = {
      'casi perfecto': 'rb-badge ok',
      'sustancial':    'rb-badge ok',
      'moderado':      'rb-badge na',
      'bajo':          'rb-badge fail',
      'leve':          'rb-badge fail',
      'peor que azar': 'rb-badge fail',
    };
    return map[i] || 'rb-badge na';
  };

  let html = `
    <table class="metric-table" style="min-width: 880px;">
      <thead>
        <tr>
          <th style="text-align:left">Ítem</th>
          <th>Tipo</th>
          <th class="col-a">κ</th>
          <th>IC 95%</th>
          <th>p₀</th>
          <th>n</th>
          <th>Alternativas</th>
          <th>Interpretación</th>
        </tr>
      </thead>
      <tbody>
  `;
  for (const it of kappa.items) {
    const alts = it.alternativas
      ? Object.entries(it.alternativas)
          .map(([k, v]) => `${k}: <span class="mono">${fmt(v, 2)}</span>`)
          .join(' · ')
      : '—';
    html += `
      <tr>
        <td class="lbl" style="text-align:left">
          ${escapeHTML(it.label)}
          ${it.nota ? `<div style="font-size:10px; color: var(--text-faint); margin-top:2px;">${escapeHTML(it.nota)}</div>` : ''}
        </td>
        <td class="lbl">${escapeHTML(it.tipo)}</td>
        <td class="val mono col-a">${fmt(it.kappa, 3)}</td>
        <td class="val mono">[${fmt(it.ic_low, 2)}, ${fmt(it.ic_high, 2)}]</td>
        <td class="val mono">${fmt(it.p_o, 3)}</td>
        <td class="val mono">${it.n}</td>
        <td class="lbl" style="font-size:11px">${alts}</td>
        <td class="lbl"><span class="${interpCls(it.interpretacion)}">${escapeHTML(it.interpretacion)}</span></td>
      </tr>
    `;
  }
  html += '</tbody></table>';
  wrap.innerHTML = html;
}

// ---------------------------------------------------------------------
// Detalle del perfil seleccionado
// ---------------------------------------------------------------------
function renderPerfilDetail(perfil) {
  const card = $('#perfil-detail');
  card.classList.remove('hidden');

  const p = perfil.profile || {};
  const cells = [
    ['Edad', p.edad],
    ['País', p.pais],
    ['Renta', p.renta],
    ['Capital', p.capital ? `${p.capital.toLocaleString('es-ES')} €` : null],
    ['Mensual', p.aportacion_mensual ? `${p.aportacion_mensual} €/mes` : null],
    ['Horizonte', p.horizonte],
    ['Riesgo', p.perfil_riesgo],
    ['Sectores', (p.sectores || []).join(', ')],
    ['Regiones', (p.regiones || []).join(', ')],
    ['Excluye', (p.excluir || []).join(', ') || '—'],
  ].filter(([_, v]) => v);

  card.innerHTML = `
    <h2>${escapeHTML(perfil.etiqueta)}</h2>
    <p class="desc">${escapeHTML(perfil.descripcion)}</p>
    <div class="estudio-perfil-grid">
      ${cells.map(([lbl, val]) => `
        <div class="estudio-perfil-cell">
          <div class="lbl">${escapeHTML(lbl)}</div>
          <div class="val">${escapeHTML(String(val))}</div>
        </div>`).join('')}
    </div>
    ${p.notas ? `
      <details class="expander mt-3">
        <summary>Notas del gestor</summary>
        <p class="text-sm mt-2" style="color: var(--text-muted)">${escapeHTML(p.notas)}</p>
      </details>` : ''}
    ${perfil.gestor_banco ? `
      <p class="text-xs mt-3" style="color: var(--vdos-blue-500)">
        Gestor: <span class="mono">${escapeHTML(perfil.gestor_banco)}</span>
      </p>` : ''}
  `;
}

// ---------------------------------------------------------------------
// Prompt box + copy button
// ---------------------------------------------------------------------
function renderPromptBox(prompt) {
  $('#prompt-box').textContent = prompt;
}

function bindActionsForPerfil(perfilId) {
  $('#btn-copy-prompt').onclick = async () => {
    try {
      await navigator.clipboard.writeText($('#prompt-box').textContent);
      setStatus('copy-status', 'Copiado al portapapeles', false);
    } catch (e) {
      setStatus('copy-status', 'No pude copiar: ' + e.message, true);
    }
    setTimeout(() => setStatus('copy-status', ''), 3000);
  };

  $('#btn-save-paste').onclick = async () => {
    const text = $('#paste-text').value;
    const modelo = $('#paste-modelo').value;
    if (!text.trim()) {
      setStatus('paste-status', 'Pega primero la respuesta', true);
      return;
    }
    setStatus('paste-status', 'Guardando…', false);
    try {
      await api.estudioPasteChatGPT(perfilId, { raw_text: text, modelo });
      setStatus('paste-status', 'Guardado y evaluado', false);
      $('#paste-text').value = '';
      await renderComparativa();
      await loadAgregado();
    } catch (e) {
      setStatus('paste-status', 'Error: ' + e.message, true);
    }
  };

  $('#btn-delete-paste').onclick = async () => {
    try {
      await api.estudioDeleteChatGPT(perfilId);
      setStatus('paste-status', 'Respuesta de ChatGPT borrada', false);
      await renderComparativa();
      await loadAgregado();
    } catch (e) {
      setStatus('paste-status', 'Error: ' + e.message, true);
    }
  };

  $('#btn-run-asesor').onclick = async () => {
    setStatus('run-status', 'Ejecutando Asesor (puede tardar 5-10s)…', false);
    const btn = $('#btn-run-asesor');
    btn.disabled = true;
    try {
      await api.estudioRunAsesor(perfilId);
      setStatus('run-status', 'Asesor ejecutado y evaluado', false);
      await renderComparativa();
      await loadAgregado();
    } catch (e) {
      setStatus('run-status', 'Error: ' + e.message, true);
    } finally {
      btn.disabled = false;
    }
  };
}

function setStatus(id, msg, isError = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg || '';
  el.style.color = isError ? 'var(--loss-700)' : 'var(--text-muted)';
}

// ---------------------------------------------------------------------
// Render de cada sistema (Asesor o ChatGPT)
// ---------------------------------------------------------------------
function renderSystemSide(which, evaluada) {
  const body = $(`#body-${which}`);
  const meta = $(`#meta-${which}`);
  const scoreWrap = $(`#score-${which}`);
  scoreWrap.innerHTML = '';

  if (!evaluada) {
    body.innerHTML = `<div class="no-data">${
      which === 'asesor'
        ? 'Pulsa “Ejecutar Asesor VDOS” arriba.'
        : 'Pega la respuesta de ChatGPT arriba.'
    }</div>`;
    meta.textContent = '— sin datos —';
    return;
  }

  const raw = evaluada.raw || {};
  meta.textContent = [
    raw.modelo || '?',
    raw.timestamp ? raw.timestamp.split('T')[0] : null,
    `${(evaluada.por_fondo || []).length} fondos`,
  ].filter(Boolean).join(' · ');

  const score = evaluada.global?.score_global ?? 0;
  const pillCls = which === 'chatgpt' ? 'score-pill-big chatgpt-bg' : 'score-pill-big';
  scoreWrap.innerHTML = `
    <div class="${pillCls}">
      <div class="num">${score.toFixed(0)}</div>
      <div class="lbl">score</div>
    </div>`;

  // Resumen ejecutivo + fondos con badges de rubrica
  const fondos = raw.fondos_recomendados || [];
  const rubricas = evaluada.por_fondo || [];
  const rubMap = Object.fromEntries(rubricas.map((r) => [r.isin, r]));

  body.innerHTML = `
    ${raw.resumen_ejecutivo ? `
      <p class="text-sm" style="color: var(--text-muted); margin-bottom: 12px;">
        ${escapeHTML(raw.resumen_ejecutivo)}
      </p>` : ''}
    <div>
      ${fondos.map((f) => renderFondoRow(f, rubMap[f.isin])).join('') ||
        '<div class="no-data">Sin fondos recomendados.</div>'}
    </div>
  `;
}

function renderFondoRow(fondo, rub) {
  const peso = fondo.peso_cartera_pct;
  const pesoStr = peso != null ? `${Math.round(peso)} %` : '';
  const badges = [];

  if (rub) {
    // "ISIN" = no alucinación: existe en la base VDOS Y el nombre cuadra.
    const isinOk = rub.isin_valido !== undefined ? rub.isin_valido : rub.existe_cnmv;
    badges.push(badge('ISIN', isinOk));
    // ISIN real pero con nombre de otro fondo => alucinación de nombre.
    if (rub.existe_cnmv && rub.nombre_coherente === false) {
      badges.push(badge('nombre≠ISIN', false));
    }
    badges.push(badge('ES', rub.es_nacional));
    if (rub.riesgo_ok !== null && rub.riesgo_ok !== undefined) {
      badges.push(badge(
        `riesgo ${rub.riesgo_observado != null ? rub.riesgo_observado : '?'}`,
        rub.riesgo_ok,
      ));
    }
    if (rub.horizonte_ok !== null && rub.horizonte_ok !== undefined) {
      badges.push(badge('plazo', rub.horizonte_ok));
    }
    if (rub.esg_ok !== null && rub.esg_ok !== undefined) {
      badges.push(badge('ESG', rub.esg_ok));
    }
  } else {
    badges.push(`<span class="rb-badge na">sin rubrica</span>`);
  }

  return `
    <div class="rubrica-fondo-row">
      <div>
        <div class="nombre">${escapeHTML(fondo.nombre || '(sin nombre)')}</div>
        <div class="isin">${escapeHTML(fondo.isin)}</div>
      </div>
      <div class="peso">${escapeHTML(pesoStr)}</div>
      <div class="badges">${badges.join('')}</div>
    </div>
    ${fondo.justificacion ? `
      <details class="expander" style="margin: 6px 0 10px 0;">
        <summary style="font-size: 11px;">justificación</summary>
        <p class="text-sm mt-1" style="color: var(--text-muted)">${escapeHTML(fondo.justificacion)}</p>
      </details>` : ''}
  `;
}

function badge(label, ok) {
  if (ok === null || ok === undefined) {
    return `<span class="rb-badge na">${escapeHTML(label)} ?</span>`;
  }
  return `<span class="rb-badge ${ok ? 'ok' : 'fail'}">${escapeHTML(label)}</span>`;
}

// ---------------------------------------------------------------------
// Barras: rubrica detallada lado a lado
// ---------------------------------------------------------------------
function renderBars(asesor, chatgpt) {
  const content = $('#bars-content');
  content.innerHTML = '';

  // 1) Metricas formales (las dos que SI tenemos y diferencian)
  // 2) Metricas cuantitativas reales del CSV VDOS
  //
  // QUITADAS: 'Adecuacion de riesgo' (PRIESGOF vacio) y 'ESG' (no medible
  // bien con keywords). REEMPLAZADAS por Sharpe, rentabilidad y comision.
  const metrics = [
    // origen: rubrica formal global[key]
    { label: 'ISIN en base VDOS + nombre coherente (no alucinación)', source: 'rubrica', key: 'pct_isins_validos', crudoFmt: null },
    { label: 'ISIN nacional (ES…)',                  source: 'rubrica', key: 'pct_nacionales',    crudoFmt: null },
    { label: 'Coherencia de horizonte',              source: 'rubrica', key: 'pct_horizonte_ok',  crudoFmt: null },
    { label: 'Cobertura sectorial',                  source: 'rubrica', key: 'cobertura_sectorial_pct', crudoFmt: null },
    // origen: cuanti_norm + cuanti raw para la cifra real
    { label: 'Sharpe medio ponderado',               source: 'cuanti',  key: 'sharpe',            crudoKey: 'sharpe',         crudoFmt: 'num' },
    { label: 'Rentabilidad 1 año media',             source: 'cuanti',  key: 'rentabilidad_1a',   crudoKey: 'rentabilidad_1a', crudoFmt: 'pct' },
    { label: 'Comisión total (menor = mejor)',       source: 'cuanti',  key: 'comision_total',    crudoKey: 'comision_total',  crudoFmt: 'pct' },
  ];

  const getNorm = (side, m) => {
    if (!side?.global) return null;
    if (m.source === 'rubrica') return side.global[m.key];
    return side.global.cuanti_norm?.[m.key];
  };
  const getCrudo = (side, m) => {
    if (m.source !== 'cuanti' || !m.crudoKey) return null;
    return side?.global?.cuanti?.[m.crudoKey];
  };
  const fmtCrudo = (v, fmt) => {
    if (v === null || v === undefined || Number.isNaN(v)) return '—';
    if (fmt === 'pct') return (v * 100).toFixed(2) + ' %';
    if (fmt === 'num') return Number(v).toFixed(2);
    return String(v);
  };

  metrics.forEach((m) => {
    const block = document.createElement('div');

    const head = document.createElement('div');
    head.className = 'metric-bar-row';
    const crudoA = getCrudo(asesor, m);
    const crudoB = getCrudo(chatgpt, m);
    const crudoStr = (m.source === 'cuanti')
      ? ` <span style="font-weight: 400; color: var(--text-muted); font-size: 11px; margin-left: 8px;">crudo → A: ${fmtCrudo(crudoA, m.crudoFmt)} · C: ${fmtCrudo(crudoB, m.crudoFmt)}</span>`
      : '';
    head.innerHTML = `<div class="lbl" style="grid-column: span 3; font-weight: 500; color: var(--vdos-blue-900);">${escapeHTML(m.label)}${crudoStr}</div>`;
    block.appendChild(head);

    block.appendChild(barRow('Asesor VDOS', getNorm(asesor, m), 'asesor'));
    block.appendChild(barRow('ChatGPT',     getNorm(chatgpt, m), 'chatgpt'));
    content.appendChild(block);
  });

  // HHI (concentracion) — sigue siendo util como dato auxiliar
  const hhi = document.createElement('div');
  hhi.className = 'mt-3 text-xs';
  hhi.style.color = 'var(--text-muted)';
  hhi.innerHTML = `
    HHI por gestoras (0 = diversa, 1 = monopolio): Asesor
    <span class="mono">${fmt(asesor?.global?.hhi_gestoras)}</span> ·
    ChatGPT <span class="mono">${fmt(chatgpt?.global?.hhi_gestoras)}</span>
  `;
  content.appendChild(hhi);
}

function barRow(label, value, kind) {
  const row = document.createElement('div');
  row.className = `metric-bar-row ${kind}`;
  const v = (typeof value === 'number') ? Math.max(0, Math.min(100, value)) : 0;
  const txt = (value === null || value === undefined) ? '—' : `${value.toFixed(0)} %`;
  row.innerHTML = `
    <div class="lbl">${escapeHTML(label)}</div>
    <div class="bar-bg"><div class="bar-fill" style="width: ${v}%"></div></div>
    <div class="val">${txt}</div>
  `;
  return row;
}

function fmt(v) {
  return (typeof v === 'number') ? v.toFixed(3) : '—';
}

// ---------------------------------------------------------------------
// Agregado: tabla + grafico
// ---------------------------------------------------------------------
async function loadAgregado() {
  try {
    const data = await api.estudioAgregado();
    renderAgregadoTable(data.rows);
    renderAgregadoChart(data.rows);
    renderResumenGlobal(data.rows);
  } catch (e) {
    $('#agregado-content').innerHTML =
      `<div class="empty" style="color: var(--loss-700)">Error: ${escapeHTML(e.message)}</div>`;
  }
}

function renderAgregadoTable(rows) {
  const c = $('#agregado-content');
  c.innerHTML = '';
  const table = document.createElement('table');
  table.className = 'agregado-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th>Perfil</th>
        <th>Asesor VDOS · score</th>
        <th>Asesor · % ISIN en base</th>
        <th>ChatGPT · score</th>
        <th>ChatGPT · % ISIN en base</th>
        <th>Ganador</th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tb = table.querySelector('tbody');
  rows.forEach((r) => {
    const aScore = r.asesor?.score_global ?? null;
    const aISIN  = r.asesor?.pct_isins_validos ?? null;
    const cScore = r.chatgpt?.score_global ?? null;
    const cISIN  = r.chatgpt?.pct_isins_validos ?? null;

    let ganador = '—';
    if (aScore !== null && cScore !== null) {
      if (aScore > cScore + 1) ganador = 'Asesor';
      else if (cScore > aScore + 1) ganador = 'ChatGPT';
      else ganador = 'Empate';
    } else if (aScore !== null) ganador = 'Asesor (solo)';
    else if (cScore !== null) ganador = 'ChatGPT (solo)';

    const tr = document.createElement('tr');
    if (ganador === 'Asesor' || ganador === 'ChatGPT') tr.classList.add('winner');
    tr.innerHTML = `
      <td>${escapeHTML(r.etiqueta)}</td>
      <td class="num asesor-cell">${aScore !== null ? aScore.toFixed(1) : '—'}</td>
      <td class="num">${aISIN !== null ? aISIN.toFixed(0) + ' %' : '—'}</td>
      <td class="num chatgpt-cell">${cScore !== null ? cScore.toFixed(1) : '—'}</td>
      <td class="num">${cISIN !== null ? cISIN.toFixed(0) + ' %' : '—'}</td>
      <td>${escapeHTML(ganador)}</td>
    `;
    tb.appendChild(tr);
  });
  c.appendChild(table);
}

function renderAgregadoChart(rows) {
  const labels = rows.map((r) => r.etiqueta);
  const aScores = rows.map((r) => r.asesor?.score_global ?? null);
  const cScores = rows.map((r) => r.chatgpt?.score_global ?? null);

  Plotly.react('agregado-chart', [
    {
      x: labels, y: aScores, type: 'bar',
      name: 'Asesor VDOS', marker: { color: '#042C53' },
    },
    {
      x: labels, y: cScores, type: 'bar',
      name: 'ChatGPT', marker: { color: '#10A37F' },
    },
  ], {
    barmode: 'group',
    margin: { l: 50, r: 10, t: 10, b: 80 },
    paper_bgcolor: '#FFFFFF',
    plot_bgcolor: '#FFFFFF',
    font: { family: 'Inter', size: 12, color: '#042C53' },
    legend: { orientation: 'h', y: -0.25 },
    yaxis: { title: 'Score global (0-100)', range: [0, 100],
             gridcolor: 'rgba(0,0,0,0.05)' },
    xaxis: { tickangle: -20, gridcolor: 'rgba(0,0,0,0.05)' },
  }, { displayModeBar: false, responsive: true });
}

// ---------------------------------------------------------------------
// Resumen global: medias sobre todos los perfiles + veredicto
// ---------------------------------------------------------------------
// Las 7 metricas DIFERENCIADORAS frente a ChatGPT, en el orden visual del
// resumen global. Son las que se basan en datos VDOS reales (alucinacion,
// historico VL, rentabilidades, Sharpe, comisiones, volatilidad).
const METRICAS_CUANTI = [
  { label: 'ISIN en base VDOS + nombre coherente (no alucinación)', cuantiKey: null, rubKey: 'pct_isins_validos',
    crudoLabel: '% ISINs en catálogo' },
  { label: 'Idoneidad al perfil (capital en banda de riesgo)', cuantiKey: 'idoneidad', rubKey: null,
    crudoKey: 'idoneidad', crudoFmt: 'pctpts' },
  { label: 'Rentabilidad 1 año media (ponderada)', cuantiKey: 'rentabilidad_1a',
    crudoKey: 'rentabilidad_1a', crudoFmt: 'pct' },
  { label: 'Rentabilidad 3 años anualizada',       cuantiKey: 'rentabilidad_3a_anual',
    crudoKey: 'rentabilidad_3a_anual', crudoFmt: 'pct' },
  { label: 'Sharpe medio ponderado',               cuantiKey: 'sharpe',
    crudoKey: 'sharpe', crudoFmt: 'num' },
  { label: 'Comisión total (menor = mejor)',       cuantiKey: 'comision_total',
    crudoKey: 'comision_total', crudoFmt: 'pct' },
  { label: 'Volatilidad media (menor = mejor)',    cuantiKey: 'volatilidad',
    crudoKey: 'volatilidad', crudoFmt: 'pct' },
];

function _fmtCrudo(v, fmt) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  if (fmt === 'pct') return (v * 100).toFixed(2) + ' %';
  if (fmt === 'pctpts') return v.toFixed(0) + ' %';  // ya viene en puntos %
  if (fmt === 'num') return v.toFixed(2);
  return String(v);
}

function _composeScore(sysData) {
  // Score = media de las 7 metricas normalizadas (cuanti_norm + no_alucinacion).
  // Penaliza ausencia (None cuenta como 0): si el sistema aluciona y no hay
  // datos historicos, el score baja.
  if (!sysData) return null;
  const cn = sysData.cuanti_norm || {};
  const valores = [
    sysData.pct_isins_validos,        // alucinacion (0-100)
    cn.idoneidad,                     // idoneidad al perfil (0-100)
    cn.rentabilidad_1a,
    cn.rentabilidad_3a_anual,
    cn.sharpe,
    cn.comision_total,
    cn.volatilidad,
  ].map((v) => (typeof v === 'number') ? v : 0);
  if (valores.length === 0) return null;
  return valores.reduce((a, b) => a + b, 0) / valores.length;
}

function renderResumenGlobal(rows) {
  const ambos = rows.filter((r) => r.asesor && r.chatgpt);
  const sec = $('#resumen-section');

  if (ambos.length === 0) {
    sec.classList.add('hidden');
    return;
  }
  sec.classList.remove('hidden');

  // Score CUANTI por sistema (media de las 7 metricas)
  const aScores = ambos.map((r) => _composeScore(r.asesor));
  const cScores = ambos.map((r) => _composeScore(r.chatgpt));
  const meanArr = (arr) => {
    const v = arr.filter((x) => typeof x === 'number');
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };
  const aScore = meanArr(aScores);
  const cScore = meanArr(cScores);
  const diff = (aScore !== null && cScore !== null) ? (aScore - cScore) : null;

  // Conteo de victorias por perfil sobre el score cuanti
  let aWins = 0, cWins = 0, ties = 0;
  ambos.forEach((r, i) => {
    const a = aScores[i];
    const c = cScores[i];
    if (a === null || c === null) return;
    if (a > c + 1) aWins++;
    else if (c > a + 1) cWins++;
    else ties++;
  });

  // Headline
  const head = $('#resumen-headline');
  head.innerHTML = `
    <div class="metric-card" style="background: var(--vdos-blue-50); border-color: var(--vdos-blue-100);">
      <div class="metric-label">Score medio cuant. · Asesor VDOS</div>
      <div class="metric-value mono">${aScore !== null ? aScore.toFixed(1) : '—'}</div>
      <div class="metric-help">${ambos.length} perfil(es) evaluado(s)</div>
    </div>
    <div class="metric-card" style="background: #E6F8F2; border-color: #B5E5D4;">
      <div class="metric-label" style="color: #0A7A5E">Score medio cuant. · ChatGPT</div>
      <div class="metric-value mono" style="color: #0A7A5E">${cScore !== null ? cScore.toFixed(1) : '—'}</div>
      <div class="metric-help">${ambos.length} perfil(es) evaluado(s)</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Diferencia (A − C)</div>
      <div class="metric-value mono" style="color: ${diff !== null && diff >= 0 ? 'var(--gain-700)' : 'var(--loss-700)'}">
        ${diff !== null ? (diff >= 0 ? '+' : '') + diff.toFixed(1) : '—'}
      </div>
      <div class="metric-help">
        Asesor ${aWins} · ChatGPT ${cWins} · Empate ${ties}
      </div>
    </div>
  `;

  // Medias por metrica (cuanti normalizadas 0-100 + valor crudo)
  const bars = $('#resumen-bars');
  bars.innerHTML = '';

  const meanCuanti = (system, m) => {
    const vals = ambos.map((r) => {
      const s = r[system];
      if (!s) return null;
      if (m.cuantiKey === null) return s[m.rubKey];  // alucinacion
      return s.cuanti_norm?.[m.cuantiKey];
    }).filter((v) => typeof v === 'number');
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };
  const meanCrudo = (system, m) => {
    if (!m.crudoKey) return null;
    const vals = ambos.map((r) => r[system]?.cuanti?.[m.crudoKey])
      .filter((v) => typeof v === 'number');
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
  };

  METRICAS_CUANTI.forEach((m) => {
    const mA = meanCuanti('asesor', m);
    const mC = meanCuanti('chatgpt', m);
    const crudoA = meanCrudo('asesor', m);
    const crudoB = meanCrudo('chatgpt', m);
    const crudoStr = (m.crudoKey)
      ? ` <span style="color: var(--text-muted); font-size: 11px; margin-left: 8px;">media cruda → A: ${_fmtCrudo(crudoA, m.crudoFmt)} · C: ${_fmtCrudo(crudoB, m.crudoFmt)}</span>`
      : '';

    const block = document.createElement('div');
    const head = document.createElement('div');
    head.className = 'metric-bar-row';
    head.innerHTML = `<div class="lbl" style="grid-column: span 3; font-weight: 500; color: var(--vdos-blue-900);">${escapeHTML(m.label)}${crudoStr}</div>`;
    block.appendChild(head);
    block.appendChild(barRow('Asesor VDOS', mA, 'asesor'));
    block.appendChild(barRow('ChatGPT',     mC, 'chatgpt'));
    bars.appendChild(block);
  });

  $('#resumen-veredicto').innerHTML = veredictoTexto({
    aScore, cScore, diff, aWins, cWins, ties, n: ambos.length,
    incompletos: rows.length - ambos.length,
  });
}

function veredictoTexto(s) {
  if (s.aScore === null || s.cScore === null) return 'Datos insuficientes.';
  const ganaA = s.diff > 1;
  const ganaC = s.diff < -1;
  const empate = !ganaA && !ganaC;

  let titular = '';
  if (ganaA) {
    titular = `El Asesor VDOS supera a ChatGPT en una media de <strong>${Math.abs(s.diff).toFixed(1)} puntos</strong> sobre 100 (${s.aScore.toFixed(1)} vs ${s.cScore.toFixed(1)}) en los ${s.n} perfiles evaluados.`;
  } else if (ganaC) {
    titular = `ChatGPT supera al Asesor VDOS en una media de <strong>${Math.abs(s.diff).toFixed(1)} puntos</strong> (${s.cScore.toFixed(1)} vs ${s.aScore.toFixed(1)}) en los ${s.n} perfiles evaluados.`;
  } else {
    titular = `Asesor y ChatGPT empatan en score medio (${s.aScore.toFixed(1)} vs ${s.cScore.toFixed(1)}, diferencia ${s.diff >= 0 ? '+' : ''}${s.diff.toFixed(1)} puntos) sobre los ${s.n} perfiles.`;
  }

  let victorias = '';
  if (s.aWins + s.cWins + s.ties > 0) {
    victorias = `Por perfiles: Asesor gana ${s.aWins}, ChatGPT gana ${s.cWins}, empate ${s.ties}.`;
  }

  const incompletos = s.incompletos > 0
    ? `Quedan ${s.incompletos} perfil(es) sin recomendación de uno de los dos sistemas; complétalos para una comparación robusta.`
    : 'Todos los perfiles tienen recomendación de ambos sistemas — comparación completa.';

  return `<p style="margin-bottom: 8px;">${titular}</p>
          <p style="margin-bottom: 8px;">${victorias}</p>
          <p style="color: var(--text-muted); font-size: 12px;">${incompletos}</p>`;
}


// ---------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------
init();
