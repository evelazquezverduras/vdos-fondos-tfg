// inicio.js — Logica de la vista Inicio. Carga KPIs, dos bar charts y estado.

import { api } from '../api.js';
import { fmtInt } from '../utils/format.js';
import { barChart } from '../components/plot.js';

const VDOS_700 = '#0C447C';
const VDOS_500 = '#185FA5';

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function renderStats(stats) {
  setText('kpi-isins', fmtInt(stats.isins));
  setText('kpi-gestoras', fmtInt(stats.gestoras));
  setText('kpi-categorias', fmtInt(stats.categorias));
}

function renderIndex(status) {
  const pill = document.getElementById('index-status');
  if (!pill) return;
  pill.classList.remove('ready', 'error');
  if (status.ready) {
    pill.classList.add('ready');
    pill.querySelector('.label').textContent =
      `Indice listo · ${fmtInt(status.docs)} docs · ${fmtInt(status.size_kb)} KB`;
  } else {
    pill.classList.add('error');
    pill.querySelector('.label').textContent =
      status.error || 'Indice no disponible';
  }
}

function renderError(target, err) {
  const el = document.getElementById(target);
  if (!el) return;
  el.innerHTML = `<div class="empty">No se pudo cargar: ${err.message}</div>`;
}

async function init() {
  // KPIs + estado del indice no dependen de Plotly, los pintamos primero.
  try {
    const stats = await api.stats();
    renderStats(stats);
  } catch (e) {
    console.error('stats', e);
    document.getElementById('kpi-grid')?.classList.add('hidden');
    document.getElementById('kpi-error').textContent = e.message;
  }

  api.indexStatus().then(renderIndex).catch((e) => {
    console.warn('index status', e);
  });

  // Cargar distribuciones en paralelo.
  const [cat, gest] = await Promise.all([
    api.distribucionCategoria().catch((e) => ({ error: e })),
    api.distribucionGestora(20).catch((e) => ({ error: e })),
  ]);

  if (cat.error) {
    renderError('chart-categoria', cat.error);
  } else {
    barChart('chart-categoria', cat, { color: VDOS_700, hoverPrefix: 'Categoría: ' });
  }

  if (gest.error) {
    renderError('chart-gestora', gest.error);
  } else {
    barChart('chart-gestora', gest, { color: VDOS_500, hoverPrefix: 'Gestora: ' });
  }
}

init();
