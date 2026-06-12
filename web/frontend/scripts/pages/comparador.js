// comparador.js — Logica de la vista Comparador.

import { api } from '../api.js';
import { mountFundSearch } from '../components/fund-search.js';
import { renderMetricTable } from '../components/metric-table.js';

// ---------------------------------------------------------------------------
// Estado de la pagina
// ---------------------------------------------------------------------------
const state = {
  selA: null,            // FundSearchHit del A elegido
  selB: null,            // idem B
  data: null,            // CompareResponse
  mode: 'base100',
  range: '5y',
  scale: 'linear',
  customDesde: null,
  customHasta: null,
};

const HISTORY_KEY = 'vdos.compare.history';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function setStatus(msg, type = 'info') {
  const el = $('#status');
  el.textContent = msg || '';
  el.style.color =
    type === 'error' ? 'var(--loss-700)'
    : type === 'ok' ? 'var(--gain-700)'
    : 'var(--text-muted)';
}

function rangeToDates(range, lastDate) {
  // lastDate: YYYY-MM-DD del max de la BD; lo recibimos del propio data.hasta
  if (range === 'max') return { desde: null, hasta: null };
  const end = lastDate ? new Date(lastDate) : new Date();
  const start = new Date(end);
  switch (range) {
    case '1m': start.setMonth(end.getMonth() - 1); break;
    case '3m': start.setMonth(end.getMonth() - 3); break;
    case '6m': start.setMonth(end.getMonth() - 6); break;
    case 'ytd': start.setFullYear(end.getFullYear(), 0, 1); break;
    case '1y': start.setFullYear(end.getFullYear() - 1); break;
    case '3y': start.setFullYear(end.getFullYear() - 3); break;
    case '5y':
    default: start.setFullYear(end.getFullYear() - 5); break;
  }
  return {
    desde: start.toISOString().slice(0, 10),
    hasta: end.toISOString().slice(0, 10),
  };
}

function pushHistory(isinA, nombreA, isinB, nombreB) {
  let list = [];
  try {
    list = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]');
  } catch { /* corrupto */ }
  const key = `${isinA}|${isinB}`;
  list = list.filter((h) => h.key !== key);
  list.unshift({ key, isinA, isinB, nombreA, nombreB, ts: Date.now() });
  list = list.slice(0, 5);
  sessionStorage.setItem(HISTORY_KEY, JSON.stringify(list));
  renderHistory();
}

function renderHistory() {
  const section = $('#history-section');
  const row = $('#history-row');
  row.innerHTML = '';
  let list = [];
  try { list = JSON.parse(sessionStorage.getItem(HISTORY_KEY) || '[]'); } catch {}
  if (list.length === 0) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  for (const h of list) {
    const chip = document.createElement('span');
    chip.className = 'history-chip';
    chip.textContent = `${h.isinA} ↔ ${h.isinB}`;
    chip.title = `${h.nombreA} vs ${h.nombreB}`;
    chip.addEventListener('click', async () => {
      // Cargar directos
      setStatus('Cargando comparación desde historial…');
      const detailA = await api.fundDetail(h.isinA);
      const detailB = await api.fundDetail(h.isinB);
      state.selA = { isin: detailA.isin, nombre: detailA.nombre };
      state.selB = { isin: detailB.isin, nombre: detailB.nombre };
      $('#search-a').value = `${detailA.isin} · ${detailA.nombre}`;
      $('#search-b').value = `${detailB.isin} · ${detailB.nombre}`;
      await loadCompare();
    });
    row.appendChild(chip);
  }
}

// ---------------------------------------------------------------------------
// Filtros y buscadores
// ---------------------------------------------------------------------------
async function bootstrapFilters() {
  try {
    const f = await api.fundFilters();
    // Conteo real (servido por la API) -> nunca hardcodeado en el HTML.
    const elCount = $('#count-con-vl');
    if (elCount && typeof f.n_con_vl === 'number') {
      elCount.textContent = f.n_con_vl.toLocaleString('es-ES');
    }
    const sTipo = $('#filter-tipo');
    f.tipos.forEach((t) => {
      const o = document.createElement('option');
      o.value = t; o.textContent = t;
      sTipo.appendChild(o);
    });
    const sG = $('#filter-gestora');
    f.gestoras.forEach((g) => {
      const o = document.createElement('option');
      o.value = g; o.textContent = g;
      sG.appendChild(o);
    });
  } catch (e) {
    setStatus('No se pudieron cargar filtros: ' + e.message, 'error');
  }
}

const getFilters = () => ({
  tipo: $('#filter-tipo').value || undefined,
  gestora: $('#filter-gestora').value || undefined,
  onlyWithBrochure: $('#filter-brochure').checked,
});

function bootstrapSearches() {
  const searchA = mountFundSearch({
    inputEl: $('#search-a'),
    dropdownEl: $('#dropdown-a'),
    label: 'A',
    getFilters,
    onSelect: (hit) => { state.selA = hit; maybeCompare(); },
  });
  const searchB = mountFundSearch({
    inputEl: $('#search-b'),
    dropdownEl: $('#dropdown-b'),
    label: 'B',
    getFilters,
    onSelect: (hit) => { state.selB = hit; maybeCompare(); },
  });

  // Re-disparar busqueda cuando cambian los filtros
  ['#filter-tipo', '#filter-gestora', '#filter-brochure'].forEach((sel) => {
    $(sel).addEventListener('change', () => {
      searchA.refresh();
      searchB.refresh();
    });
  });

  return { searchA, searchB };
}

async function maybeCompare() {
  if (!state.selA || !state.selB) return;
  if (state.selA.isin === state.selB.isin) {
    setStatus('Elige dos fondos distintos.', 'error');
    return;
  }
  await loadCompare();
}

// ---------------------------------------------------------------------------
// Carga y render principal
// ---------------------------------------------------------------------------
async function loadCompare() {
  setStatus('Calculando comparativa…');
  $('#result').classList.add('hidden');
  const { desde, hasta } = rangeToDates(state.range, null);
  try {
    const body = { isin_a: state.selA.isin, isin_b: state.selB.isin };
    if (desde) body.desde = desde;
    if (hasta) body.hasta = hasta;
    const data = await api.compare(body);
    state.data = data;
    pushHistory(data.isin_a, data.fund_a.nombre, data.isin_b, data.fund_b.nombre);
    renderAll();
    setStatus(
      `Comparativa lista · ${data.n_alineados} fechas comunes en ${data.desde} → ${data.hasta}`,
      'ok'
    );
    $('#result').classList.remove('hidden');
  } catch (e) {
    setStatus(e.message, 'error');
  }
}

function renderAll() {
  renderHeader('#fund-header-a', state.data.fund_a, 'A');
  renderHeader('#fund-header-b', state.data.fund_b, 'B');
  renderMainChart();
  renderMetricTables();
  renderDerived();
  renderBrochure();
}

// ---------------------------------------------------------------------------
// Cabeceras de fondo
// ---------------------------------------------------------------------------
function renderHeader(sel, fund, label) {
  const el = $(sel);
  el.innerHTML = '';

  const meta = document.createElement('div');
  meta.className = 'fund-header-meta';
  meta.textContent = `${label} · ${fund.gestora || 's/g'} · ${fund.isin}`;
  el.appendChild(meta);

  const name = document.createElement('div');
  name.className = 'fund-header-name';
  name.textContent = fund.nombre;
  el.appendChild(name);

  const sub = document.createElement('div');
  sub.className = 'fund-header-sub';
  const subParts = [];
  if (fund.tipo) subParts.push(fund.tipo);
  if (fund.cat_macro) subParts.push(fund.cat_macro);
  if (fund.depositaria) subParts.push(`Dep.: ${fund.depositaria}`);
  if (fund.structure?.fecha_snapshot) subParts.push(`Snapshot: ${fund.structure.fecha_snapshot}`);
  sub.textContent = subParts.join(' · ');
  el.appendChild(sub);

  // Chips de categoria del folleto si esta disponible
  if (fund.brochure) {
    const chips = document.createElement('div');
    chips.className = 'flex flex-wrap gap-1 pt-1';
    const variants = [
      ['p00', fund.brochure.p00_label],
      ['p05', fund.brochure.p05_label],
      ['p06', fund.brochure.p06_label],
    ];
    variants.forEach(([variant, text]) => {
      if (text) {
        const c = document.createElement('span');
        c.className = `chip chip-${variant}`;
        c.textContent = text;
        chips.appendChild(c);
      }
    });
    if (fund.brochure.garant === 1) {
      const g = document.createElement('span');
      g.className = 'chip chip-sector';
      g.textContent = 'Garantizado';
      chips.appendChild(g);
    }
    el.appendChild(chips);
  }

  // Badge descatalogado
  if (fund.descatalogado) {
    const warn = document.createElement('span');
    warn.className = 'badge-warn';
    warn.textContent = 'Snapshot > 365 días — datos quizá desactualizados';
    el.appendChild(warn);
  }
}

// ---------------------------------------------------------------------------
// Grafico principal
// ---------------------------------------------------------------------------
function renderMainChart() {
  const { series_a, series_b, fund_a, fund_b } = state.data;
  const y = state.mode; // base100 | vl | ret_acum | drawdown
  const yA = series_a[y];
  const yB = series_b[y];

  const traceA = {
    x: series_a.fechas,
    y: yA,
    mode: 'lines',
    name: `A · ${fund_a.isin}`,
    line: { color: '#042C53', width: 2 },
    hovertemplate: '%{x}<br><b>A</b>: %{y:.4f}<extra></extra>',
  };
  const traceB = {
    x: series_b.fechas,
    y: yB,
    mode: 'lines',
    name: `B · ${fund_b.isin}`,
    line: { color: '#378ADD', width: 2 },
    hovertemplate: '%{x}<br><b>B</b>: %{y:.4f}<extra></extra>',
  };

  const yTitleMap = {
    base100: 'Base 100',
    vl: 'VL (EUR)',
    ret_acum: 'Rent. acumulada (%)',
    drawdown: 'Drawdown (%)',
  };

  const layout = {
    margin: { l: 60, r: 20, t: 20, b: 50 },
    paper_bgcolor: '#FFFFFF',
    plot_bgcolor: '#FFFFFF',
    font: { family: 'Inter, system-ui, sans-serif', size: 12, color: '#042C53' },
    legend: { orientation: 'h', y: -0.18, x: 0 },
    xaxis: { gridcolor: 'rgba(0,0,0,0.05)', linecolor: 'rgba(0,0,0,0.15)' },
    yaxis: {
      title: yTitleMap[y],
      type: state.scale === 'log' && (y === 'vl' || y === 'base100') ? 'log' : 'linear',
      gridcolor: 'rgba(0,0,0,0.05)',
      linecolor: 'rgba(0,0,0,0.15)',
      zeroline: y === 'drawdown' || y === 'ret_acum',
      zerolinecolor: 'rgba(0,0,0,0.2)',
    },
  };

  Plotly.react('chart-main', [traceA, traceB], layout, {
    displayModeBar: false,
    responsive: true,
  });
}

// ---------------------------------------------------------------------------
// Tablas de métricas
// ---------------------------------------------------------------------------
function renderMetricTables() {
  const { fund_a, fund_b } = state.data;

  // 1) Rentabilidades acumuladas
  renderMetricTable($('#table-returns'), {
    title: 'Rentabilidades acumuladas',
    rows: [
      { label: '1 mes',   a: fund_a.returns.r1m,  b: fund_b.returns.r1m,  fmt: 'pct', better: 'higher' },
      { label: '3 meses', a: fund_a.returns.r3m,  b: fund_b.returns.r3m,  fmt: 'pct', better: 'higher' },
      { label: '6 meses', a: fund_a.returns.r6m,  b: fund_b.returns.r6m,  fmt: 'pct', better: 'higher' },
      { label: '1 año',   a: fund_a.returns.r1a,  b: fund_b.returns.r1a,  fmt: 'pct', better: 'higher' },
      { label: '3 años',  a: fund_a.returns.r3a,  b: fund_b.returns.r3a,  fmt: 'pct', better: 'higher' },
      { label: '5 años',  a: fund_a.returns.r5a,  b: fund_b.returns.r5a,  fmt: 'pct', better: 'higher' },
      { label: 'YTD',     a: fund_a.returns.ytd1, b: fund_b.returns.ytd1, fmt: 'pct', better: 'higher' },
      { label: 'Desde inicio', a: fund_a.returns.rinicio, b: fund_b.returns.rinicio, fmt: 'pct', better: 'higher' },
    ],
  });

  // 2) Riesgo
  renderMetricTable($('#table-risk'), {
    title: 'Riesgo',
    rows: [
      { label: 'Volatilidad',     a: fund_a.risk.volatilidad, b: fund_b.risk.volatilidad, fmt: 'pct', better: 'lower' },
      { label: 'Sharpe',          a: fund_a.risk.sharpe,      b: fund_b.risk.sharpe,      fmt: 'num', better: 'higher' },
      { label: 'Tracking error',  a: fund_a.risk.tracking_error, b: fund_b.risk.tracking_error, fmt: 'pct', better: 'lower' },
      { label: 'Max DD (rango)',  a: fund_a.risk.max_drawdown, b: fund_b.risk.max_drawdown, fmt: 'num', better: 'lower' },
    ],
  });

  // 3) Comisiones
  renderMetricTable($('#table-fees'), {
    title: 'Comisiones',
    rows: [
      { label: 'Gestión',     a: fund_a.fees.com_gestion,     b: fund_b.fees.com_gestion,     fmt: 'pct4', better: 'lower' },
      { label: 'Depositario', a: fund_a.fees.com_depositario, b: fund_b.fees.com_depositario, fmt: 'pct4', better: 'lower' },
      { label: 'Total recurrente (anual)', a: fund_a.fees.com_total, b: fund_b.fees.com_total, fmt: 'pct4', better: 'lower' },
      { label: 'Reembolso (máx., puntual)', a: fund_a.fees.com_reembolso, b: fund_b.fees.com_reembolso, fmt: 'pct4', better: 'lower' },
      { label: 'Retrocesión', a: fund_a.fees.retrocesion,     b: fund_b.fees.retrocesion,     fmt: 'pct4', better: null },
    ],
  });
  renderFeesChart();

  // 4) Estructura
  renderMetricTable($('#table-structure'), {
    title: 'Estructura del fondo',
    rows: [
      { label: 'VL actual (EUR)',       a: fund_a.structure.vl, b: fund_b.structure.vl, fmt: 'num4', better: null },
      { label: 'Patrimonio (EUR)',      a: fund_a.structure.patrimonio_miles, b: fund_b.structure.patrimonio_miles, fmt: 'eur_k', better: 'higher' },
      { label: 'Partícipes',            a: fund_a.structure.participaciones,  b: fund_b.structure.participaciones,  fmt: 'int', better: 'higher' },
      { label: 'Aportación mínima',     a: fund_a.structure.aportacion_minima, b: fund_b.structure.aportacion_minima, fmt: 'num', better: 'lower' },
      { label: 'Fecha registro',        a: fund_a.structure.fecha_registro, b: fund_b.structure.fecha_registro, fmt: 'str', better: null },
      { label: 'Snapshot',              a: fund_a.structure.fecha_snapshot, b: fund_b.structure.fecha_snapshot, fmt: 'str', better: null },
    ],
  });

  // 5) Anualizadas (avanzado)
  renderMetricTable($('#table-ann'), {
    title: 'Rentabilidades anualizadas',
    rows: [
      { label: 'Anualizada total', a: fund_a.returns.ra,  b: fund_b.returns.ra,  fmt: 'pct', better: 'higher' },
      { label: 'Anual. 1 año',     a: fund_a.returns.ra1, b: fund_b.returns.ra1, fmt: 'pct', better: 'higher' },
      { label: 'Anual. 3 años',    a: fund_a.returns.ra3, b: fund_b.returns.ra3, fmt: 'pct', better: 'higher' },
      { label: 'Anual. 5 años',    a: fund_a.returns.ra5, b: fund_b.returns.ra5, fmt: 'pct', better: 'higher' },
    ],
  });

  // 6) Análisis vs benchmark (avanzado)
  renderMetricTable($('#table-bench'), {
    title: 'Análisis vs benchmark',
    rows: [
      { label: 'Alfa',         a: fund_a.risk.alfa,      b: fund_b.risk.alfa,      fmt: 'num4', better: 'higher' },
      { label: 'Beta',         a: fund_a.risk.beta,      b: fund_b.risk.beta,      fmt: 'num',  better: null },
      { label: 'R²',           a: fund_a.risk.r_cuadrado, b: fund_b.risk.r_cuadrado, fmt: 'num',  better: 'higher' },
      { label: 'Ratio info.',  a: fund_a.risk.ratio_info, b: fund_b.risk.ratio_info, fmt: 'num',  better: 'higher' },
    ],
  });

  // 7) Cuartiles (avanzado)
  renderMetricTable($('#table-quart'), {
    title: 'Cuartiles VDOS',
    rows: [
      { label: 'Cuartil 1m', a: fund_a.quartiles.qr1m, b: fund_b.quartiles.qr1m, fmt: 'str', better: null },
      { label: 'Cuartil 3m', a: fund_a.quartiles.qr3m, b: fund_b.quartiles.qr3m, fmt: 'str', better: null },
      { label: 'Cuartil 1a', a: fund_a.quartiles.qr1a, b: fund_b.quartiles.qr1a, fmt: 'str', better: null },
      { label: 'Cuartil 3a', a: fund_a.quartiles.qr3a, b: fund_b.quartiles.qr3a, fmt: 'str', better: null },
      { label: 'Cuartil 5a', a: fund_a.quartiles.qr5a, b: fund_b.quartiles.qr5a, fmt: 'str', better: null },
      { label: 'Pos. 1a',    a: fund_a.quartiles.prr1a, b: fund_b.quartiles.prr1a, fmt: 'str', better: null },
      { label: 'Pos. 3a',    a: fund_a.quartiles.prr3a, b: fund_b.quartiles.prr3a, fmt: 'str', better: null },
      { label: 'Pos. 5a',    a: fund_a.quartiles.prr5a, b: fund_b.quartiles.prr5a, fmt: 'str', better: null },
    ],
  });
}

function renderFeesChart() {
  const { fund_a, fund_b } = state.data;
  // Solo comisiones RECURRENTES (anuales). El reembolso es una penalizacion
  // puntual y condicional (puede ser 6-9%): si se incluye aqui, su barra
  // aplasta al resto y da una lectura enganosa. Se muestra solo en la tabla.
  const cats = ['Gestión', 'Depositario', 'Total'];
  const valsA = [
    fund_a.fees.com_gestion ?? 0,
    fund_a.fees.com_depositario ?? 0,
    fund_a.fees.com_total ?? 0,
  ].map((v) => v * 100);
  const valsB = [
    fund_b.fees.com_gestion ?? 0,
    fund_b.fees.com_depositario ?? 0,
    fund_b.fees.com_total ?? 0,
  ].map((v) => v * 100);
  Plotly.react('chart-fees', [
    { x: cats, y: valsA, type: 'bar', name: 'A', marker: { color: '#042C53' } },
    { x: cats, y: valsB, type: 'bar', name: 'B', marker: { color: '#378ADD' } },
  ], {
    margin: { l: 40, r: 10, t: 10, b: 36 },
    paper_bgcolor: '#FFFFFF',
    plot_bgcolor: '#FFFFFF',
    barmode: 'group',
    font: { family: 'Inter', size: 11, color: '#042C53' },
    legend: { orientation: 'h', y: -0.25 },
    yaxis: { title: '%', gridcolor: 'rgba(0,0,0,0.05)' },
    xaxis: { gridcolor: 'rgba(0,0,0,0.05)' },
  }, { displayModeBar: false, responsive: true });
}

// ---------------------------------------------------------------------------
// Análisis derivado: tarjetas + rolling + histograma
// ---------------------------------------------------------------------------
function renderDerived() {
  const d = state.data.derived;
  const cards = $('#derived-cards');
  cards.innerHTML = '';

  const cards_data = [
    {
      label: 'Correlación de retornos',
      value: d.correlacion === null ? '—' : d.correlacion.toFixed(3),
      help: d.correlacion === null
        ? 'No hay suficientes observaciones alineadas.'
        : d.correlacion > 0.8 ? 'Muy correlacionados: se mueven casi a la par.'
        : d.correlacion > 0.4 ? 'Correlación moderada.'
        : d.correlacion > 0   ? 'Baja correlación: buen candidato para diversificar.'
        :                       'Anticorrelados: se mueven en sentidos opuestos.',
    },
    {
      label: 'Beta de A respecto a B',
      value: d.beta_a_vs_b === null ? '—' : d.beta_a_vs_b.toFixed(3),
      help: d.beta_a_vs_b === null
        ? 'Datos insuficientes.'
        : `α (diario) = ${(d.alpha_a_vs_b ?? 0).toExponential(2)} · n=${d.n_observations}`,
    },
    {
      label: 'Observaciones',
      value: String(d.n_observations),
      help: 'Días con retornos válidos en ambas series.',
    },
    {
      label: 'Histórico común',
      value: `${state.data.n_alineados} días`,
      help: `${state.data.desde} → ${state.data.hasta}`,
    },
  ];

  cards_data.forEach((c) => {
    const div = document.createElement('div');
    div.className = 'derived-card';
    div.innerHTML = `
      <div class="derived-label">${c.label}</div>
      <div class="derived-value">${c.value}</div>
      <div class="derived-help">${c.help}</div>
    `;
    cards.appendChild(div);
  });

  // Rolling vol 60d
  const rA = d.rolling_vol_a;
  const rB = d.rolling_vol_b;
  Plotly.react('chart-rolling', [
    { x: rA.fechas, y: rA.vol60, mode: 'lines', name: 'A', line: { color: '#042C53', width: 2 } },
    { x: rB.fechas, y: rB.vol60, mode: 'lines', name: 'B', line: { color: '#378ADD', width: 2 } },
  ], {
    margin: { l: 50, r: 10, t: 10, b: 36 },
    paper_bgcolor: '#FFFFFF',
    plot_bgcolor: '#FFFFFF',
    font: { family: 'Inter', size: 11, color: '#042C53' },
    legend: { orientation: 'h', y: -0.2 },
    yaxis: { tickformat: '.0%', gridcolor: 'rgba(0,0,0,0.05)' },
    xaxis: { gridcolor: 'rgba(0,0,0,0.05)' },
  }, { displayModeBar: false, responsive: true });

  // Histograma de retornos (con bins COMUNES desde el backend para que
  // las barras se puedan superponer comparativamente).
  renderHistograma(d.histograma_a, d.histograma_b);
}


function renderHistograma(hA, hB) {
  if (!hA?.bin_edges?.length || !hB?.bin_edges?.length) {
    Plotly.react('chart-hist', [], {
      annotations: [{
        text: 'Sin datos suficientes para histograma',
        x: 0.5, y: 0.5, xref: 'paper', yref: 'paper',
        showarrow: false,
      }],
    }, { displayModeBar: false });
    return;
  }
  // Los bin_edges deberian ser identicos en A y B (backend histograms_dual)
  const edges = hA.bin_edges;
  const centers = edges.slice(0, -1).map((e, i) => (e + edges[i + 1]) / 2);
  const width = edges.length > 1 ? (edges[1] - edges[0]) : 0.001;

  const mean = (counts, cs) => {
    const total = counts.reduce((a, b) => a + b, 0);
    if (total === 0) return null;
    return cs.reduce((acc, c, i) => acc + c * counts[i], 0) / total;
  };
  const mA = mean(hA.counts, centers);
  const mB = mean(hB.counts, centers);

  // Cap del eje Y: si hay un pico que aplasta el resto (tipico en
  // fondos monetarios/RF corto donde la mayoria de retornos = 0%),
  // recortamos el eje Y al percentil 95 de TODOS los counts no-cero,
  // pintamos las barras tope con borde rojo y anotamos el real.
  const allCounts = [...hA.counts, ...hB.counts].filter((c) => c > 0).sort((a, b) => a - b);
  const realMax = Math.max(...hA.counts, ...hB.counts);
  let yCap = realMax * 1.1;
  let capped = false;
  if (allCounts.length >= 5) {
    const p95 = allCounts[Math.floor(allCounts.length * 0.95)];
    if (realMax > p95 * 4) {
      yCap = p95 * 1.3;
      capped = true;
    }
  }

  // Anotaciones para barras que sobrepasan el cap
  const overflowAnnotations = [];
  if (capped) {
    hA.counts.forEach((c, i) => {
      if (c > yCap) {
        overflowAnnotations.push({
          x: centers[i], y: yCap * 0.97,
          text: `${c}`, showarrow: true, arrowhead: 2, ax: 0, ay: -20,
          font: { size: 10, color: '#042C53' },
          arrowcolor: '#042C53',
        });
      }
    });
    hB.counts.forEach((c, i) => {
      if (c > yCap) {
        overflowAnnotations.push({
          x: centers[i], y: yCap * 0.85,
          text: `${c}`, showarrow: true, arrowhead: 2, ax: 0, ay: -20,
          font: { size: 10, color: '#185FA5' },
          arrowcolor: '#185FA5',
        });
      }
    });
  }

  const shapes = [];
  if (mA !== null) shapes.push({
    type: 'line', x0: mA, x1: mA, y0: 0, y1: yCap,
    line: { color: '#042C53', width: 2, dash: 'dash' },
  });
  if (mB !== null) shapes.push({
    type: 'line', x0: mB, x1: mB, y0: 0, y1: yCap,
    line: { color: '#378ADD', width: 2, dash: 'dash' },
  });

  Plotly.react('chart-hist', [
    {
      x: centers, y: hA.counts, width: width * 0.95,
      type: 'bar', name: 'Fondo A',
      marker: { color: 'rgba(4, 44, 83, 0.55)', line: { width: 0 } },
      hovertemplate: 'A: %{x:.3%}<br>%{y} días<extra></extra>',
    },
    {
      x: centers, y: hB.counts, width: width * 0.95,
      type: 'bar', name: 'Fondo B',
      marker: { color: 'rgba(55, 138, 221, 0.55)', line: { width: 0 } },
      hovertemplate: 'B: %{x:.3%}<br>%{y} días<extra></extra>',
    },
  ], {
    margin: { l: 50, r: 10, t: 30, b: 40 },
    paper_bgcolor: '#FFFFFF',
    plot_bgcolor: '#FFFFFF',
    barmode: 'overlay',
    bargap: 0,
    bargroupgap: 0,
    font: { family: 'Inter', size: 11, color: '#042C53' },
    legend: { orientation: 'h', y: -0.2 },
    xaxis: {
      title: 'Retorno diario',
      tickformat: '.2%',
      gridcolor: 'rgba(0,0,0,0.05)',
      zeroline: true,
      zerolinecolor: 'rgba(0,0,0,0.3)',
      zerolinewidth: 1,
    },
    yaxis: {
      title: 'Frecuencia (días)' + (capped ? ' · escala recortada' : ''),
      gridcolor: 'rgba(0,0,0,0.05)',
      range: [0, yCap],
    },
    shapes,
    annotations: [
      mA !== null && {
        x: mA, y: yCap, text: `μ A: ${(mA * 100).toFixed(3)}%`,
        showarrow: false, font: { size: 10, color: '#042C53' },
        xanchor: 'left', yanchor: 'top',
      },
      mB !== null && {
        x: mB, y: yCap * 0.92,
        text: `μ B: ${(mB * 100).toFixed(3)}%`,
        showarrow: false, font: { size: 10, color: '#185FA5' },
        xanchor: 'left', yanchor: 'top',
      },
      ...overflowAnnotations,
    ].filter(Boolean),
  }, { displayModeBar: false, responsive: true });
}

// ---------------------------------------------------------------------------
// Política CNMV
// ---------------------------------------------------------------------------
function renderBrochure() {
  const { fund_a, fund_b } = state.data;
  const section = $('#brochure-section');
  const wrapA = $('#brochure-a-wrap');
  const wrapB = $('#brochure-b-wrap');
  const elA = $('#brochure-a');
  const elB = $('#brochure-b');

  const has_any = (fund_a.brochure && fund_a.brochure.coment) || (fund_b.brochure && fund_b.brochure.coment);
  if (!has_any) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');

  if (fund_a.brochure?.coment) {
    elA.innerHTML = `
      <div class="citation-text">${escapeHtml(fund_a.brochure.coment)}</div>
      <div class="citation-provenance">Folleto CNMV · ${fund_a.isin}</div>`;
    wrapA.style.display = '';
  } else {
    wrapA.style.display = 'none';
  }

  if (fund_b.brochure?.coment) {
    elB.innerHTML = `
      <div class="citation-text">${escapeHtml(fund_b.brochure.coment)}</div>
      <div class="citation-provenance">Folleto CNMV · ${fund_b.isin}</div>`;
    wrapB.style.display = '';
  } else {
    wrapB.style.display = 'none';
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

// ---------------------------------------------------------------------------
// Toggles de modo / rango / escala
// ---------------------------------------------------------------------------
function bindToggles() {
  $$('.toggle-btn[data-mode]').forEach((btn) => {
    btn.addEventListener('click', () => {
      $$('.toggle-btn[data-mode]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.mode = btn.dataset.mode;
      if (state.data) renderMainChart();
    });
  });
  $$('.toggle-btn[data-scale]').forEach((btn) => {
    btn.addEventListener('click', () => {
      $$('.toggle-btn[data-scale]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.scale = btn.dataset.scale;
      if (state.data) renderMainChart();
    });
  });
  $$('.toggle-btn[data-range]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      $$('.toggle-btn[data-range]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.range = btn.dataset.range;
      if (state.selA && state.selB) await loadCompare();
    });
  });
}

// ---------------------------------------------------------------------------
// Resumen IA + Exports
// ---------------------------------------------------------------------------
function bindActions() {
  $('#btn-summary').addEventListener('click', async () => {
    if (!state.data) return;
    const block = $('#summary-block');
    const btn = $('#btn-summary');
    btn.disabled = true;
    block.innerHTML = '<span class="spinner"></span> Generando…';
    try {
      const r = await api.compareSummary({
        isin_a: state.data.isin_a,
        isin_b: state.data.isin_b,
        desde: state.data.desde,
        hasta: state.data.hasta,
      });
      block.style.color = 'var(--vdos-blue-900)';
      // simple paragraph render
      block.innerHTML = r.text
        .split(/\n\n+/)
        .map((p) => `<p style="margin-bottom: 8px;">${escapeHtml(p).replace(/\n/g, '<br>')}</p>`)
        .join('');
    } catch (e) {
      block.style.color = 'var(--loss-700)';
      block.textContent = 'No se pudo generar: ' + e.message;
    } finally {
      btn.disabled = false;
    }
  });

  $('#btn-export-json').addEventListener('click', () => {
    if (!state.data) return;
    const blob = new Blob([JSON.stringify(state.data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `compare_${state.data.isin_a}_${state.data.isin_b}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });

  $('#btn-export-pdf').addEventListener('click', () => {
    alert('Export a PDF: pendiente. Por ahora descarga el JSON.');
  });
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------
(async function init() {
  setStatus('Cargando filtros…');
  renderHistory();
  await bootstrapFilters();
  bootstrapSearches();
  bindToggles();
  bindActions();
  setStatus('Selecciona dos fondos para empezar.');
})();
